#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bip_utils import (
    Bip39MnemonicGenerator,
    Bip39MnemonicValidator,
    Bip39SeedGenerator,
    Bip39WordsNum,
    Bip44,
    Bip44Changes,
    Bip44Coins,
)
from eth_account import Account
from solders.keypair import Keypair
from web3 import Web3

getcontext().prec = 78

SCRIPT_DIR = Path(__file__).resolve().parent
TOKENS_REFERENCE = SCRIPT_DIR / "main_tokens.json"
STORAGE_DIR = Path(os.environ.get("UXUY_WALLET_HOME", Path.home() / ".uxuy-wallet")).expanduser()
MNEMONIC_FILE = STORAGE_DIR / ".mnemonic"
PRIVATE_FILE = STORAGE_DIR / ".private"
TOKENS_FILE = STORAGE_DIR / ".tokens"
ACCOUNTS_FILE = STORAGE_DIR / ".accounts"
ACTIVE_ACCOUNT_FILE = STORAGE_DIR / ".active"
SECRETS_FILE = STORAGE_DIR / ".secrets"

EVM_CHAINS = {"bsc", "base", "ethereum"}
SUPPORTED_CHAINS = EVM_CHAINS | {"solana"}
RPC_ENV_VARS = {
    "bsc": "BSC_RPC_URL",
    "base": "BASE_RPC_URL",
    "ethereum": "ETHEREUM_RPC_URL",
    "solana": "SOLANA_RPC_URL",
}
TRACKED_TOKEN_CHAINS = {
    "bsc": "BNB Smart Chain",
    "base": "Base",
    "ethereum": "Ethereum",
    "solana": "Solana",
}
NATIVE_ASSETS = {
    "bsc": {"name": "BNB", "symbol": "BNB", "decimals": 18},
    "base": {"name": "Ether", "symbol": "ETH", "decimals": 18},
    "ethereum": {"name": "Ether", "symbol": "ETH", "decimals": 18},
    "solana": {"name": "Solana", "symbol": "SOL", "decimals": 9},
}
SOLANA_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


class WalletError(Exception):
    pass


def ensure_storage_dir() -> None:
    STORAGE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STORAGE_DIR, 0o700)


def normalize_chain(value: str) -> str:
    chain = value.strip().lower()
    aliases = {"bnb": "bsc", "bnbchain": "bsc", "eth": "ethereum"}
    chain = aliases.get(chain, chain)
    if chain not in SUPPORTED_CHAINS:
        raise WalletError(f"Unsupported chain: {value}")
    return chain


def write_text_secret(path: Path, value: str) -> None:
    ensure_storage_dir()
    path.write_text(value.strip() + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def write_json(path: Path, value: Any) -> None:
    ensure_storage_dir()
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def read_text(path: Path, label: str) -> str:
    if not path.exists():
        raise WalletError(f"Missing {label}: {path}")
    return path.read_text(encoding="utf-8").strip()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=True))


def mask_secret(value: str) -> str:
    if len(value) <= 12:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


def mask_mnemonic(value: str) -> str:
    words = value.split()
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    if len(words) == 2:
        return f"{words[0]} ... {words[1]}"
    return f"{words[0]} {words[1]} ... {words[-1]} ({len(words)} words)"


def format_units(raw_value: int | str, decimals: int) -> str:
    value = Decimal(int(raw_value)) / (Decimal(10) ** decimals)
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def read_secret_value(value: str | None, use_stdin: bool, label: str) -> str:
    if bool(value) == bool(use_stdin):
        raise WalletError(f"Provide exactly one of --value or --stdin for {label}")
    if value is not None:
        return value.strip()
    return sys.stdin.read().strip()


def validate_mnemonic(mnemonic: str) -> str:
    normalized = " ".join(mnemonic.strip().split())
    Bip39MnemonicValidator().Validate(normalized)
    return normalized


def generate_mnemonic() -> str:
    return str(Bip39MnemonicGenerator().FromWordsNumber(Bip39WordsNum.WORDS_NUM_12))


def load_private_store() -> dict[str, Any]:
    return read_json(PRIVATE_FILE, {})


def save_private_store(store: dict[str, Any]) -> None:
    write_json(PRIVATE_FILE, store)


def load_local_tokens() -> list[dict[str, Any]]:
    raw = read_json(TOKENS_FILE, [])
    if not isinstance(raw, list):
        raise WalletError(f"Invalid token cache format: {TOKENS_FILE}")
    return raw


def save_local_tokens(tokens: list[dict[str, Any]]) -> None:
    write_json(TOKENS_FILE, tokens)


def load_secret_store() -> list[dict[str, Any]]:
    raw = read_json(SECRETS_FILE, [])
    if not isinstance(raw, list):
        raise WalletError(f"Invalid secrets format: {SECRETS_FILE}")
    return raw


def save_secret_store(secrets_store: list[dict[str, Any]]) -> None:
    write_json(SECRETS_FILE, secrets_store)


def load_accounts() -> list[dict[str, Any]]:
    raw = read_json(ACCOUNTS_FILE, [])
    if not isinstance(raw, list):
        raise WalletError(f"Invalid accounts format: {ACCOUNTS_FILE}")
    return raw


def save_accounts(accounts: list[dict[str, Any]]) -> None:
    write_json(ACCOUNTS_FILE, accounts)


def load_active_account_name() -> str | None:
    raw = read_json(ACTIVE_ACCOUNT_FILE, {})
    if not isinstance(raw, dict):
        raise WalletError(f"Invalid active account format: {ACTIVE_ACCOUNT_FILE}")
    name = str(raw.get("name", "")).strip()
    return name or None


def save_active_account_name(name: str) -> None:
    write_json(ACTIVE_ACCOUNT_FILE, {"name": name})


def normalize_account_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise WalletError("Account name is required")
    return name


def normalize_derivation_index(value: int) -> int:
    index = int(value)
    if index < 0:
        raise WalletError("Derivation index must be zero or greater")
    return index


def default_secret_name(source_type: str, chain: str | None = None) -> str:
    if source_type == "mnemonic":
        return "default-mnemonic"
    if source_type == "private":
        normalized = normalize_chain(chain or "ethereum")
        return "default-evm-private" if normalized in EVM_CHAINS else "default-solana-private"
    raise WalletError(f"Unsupported secret type: {source_type}")


def normalize_secret_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise WalletError("Secret name is required")
    return name


def normalize_private_scope(chain: str) -> str:
    normalized = normalize_chain(chain)
    return "evm" if normalized in EVM_CHAINS else "solana"


def secret_matches_chain(secret_record: dict[str, Any], chain: str) -> bool:
    chain = normalize_chain(chain)
    if secret_record["type"] == "mnemonic":
        return True
    scope = secret_record.get("scope", "")
    return (scope == "evm" and chain in EVM_CHAINS) or (scope == "solana" and chain == "solana")


def find_secret(name: str) -> dict[str, Any]:
    target = normalize_secret_name(name)
    for secret_record in load_secret_store():
        if secret_record.get("name") == target:
            return secret_record
    raise WalletError(f"Unknown secret: {target}")


def find_secret_optional(name: str) -> dict[str, Any] | None:
    try:
        return find_secret(name)
    except WalletError:
        return None


def upsert_secret(secret_record: dict[str, Any]) -> None:
    secrets_store = load_secret_store()
    target_name = secret_record["name"]
    for index, existing in enumerate(secrets_store):
        if existing.get("name") == target_name:
            secrets_store[index] = secret_record
            save_secret_store(secrets_store)
            return
    secrets_store.append(secret_record)
    save_secret_store(secrets_store)


def secret_summary(secret_record: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": secret_record["name"],
        "type": secret_record["type"],
        "scope": secret_record.get("scope"),
        "created_at": secret_record.get("created_at"),
        "masked": secret_record.get("masked"),
    }


def remember_secret(
    name: str,
    source_type: str,
    value: str,
    chain: str | None = None,
) -> dict[str, Any]:
    name = normalize_secret_name(name)
    created_at = datetime.now(timezone.utc).isoformat()
    if source_type == "mnemonic":
        record = {
            "name": name,
            "type": "mnemonic",
            "value": validate_mnemonic(value),
            "scope": "all",
            "masked": mask_mnemonic(value),
            "created_at": created_at,
        }
    elif source_type == "private":
        normalized_chain = normalize_chain(chain or "")
        scope = normalize_private_scope(normalized_chain)
        if scope == "evm":
            private_key = value if value.startswith("0x") else f"0x{value}"
            address = evm_account_from_private_key(private_key).address
            masked = mask_secret(private_key)
            normalized_value = private_key
        else:
            keypair = solana_keypair_from_private_value(value)
            address = str(keypair.pubkey())
            masked = mask_secret(str(keypair))
            normalized_value = str(keypair)
        record = {
            "name": name,
            "type": "private",
            "scope": scope,
            "value": normalized_value,
            "masked": masked,
            "address": address,
            "created_at": created_at,
        }
    else:
        raise WalletError(f"Unsupported secret type: {source_type}")

    upsert_secret(record)
    return record


def list_secrets_with_legacy() -> list[dict[str, Any]]:
    secrets_store = [secret_summary(item) for item in load_secret_store()]
    if MNEMONIC_FILE.exists():
        mnemonic = read_text(MNEMONIC_FILE, "mnemonic")
        secrets_store.append(
            {
                "name": default_secret_name("mnemonic"),
                "type": "mnemonic",
                "scope": "all",
                "created_at": None,
                "masked": mask_mnemonic(mnemonic),
                "legacy": True,
            }
        )
    private_store = load_private_store()
    if "evm" in private_store:
        secrets_store.append(
            {
                "name": default_secret_name("private", "ethereum"),
                "type": "private",
                "scope": "evm",
                "created_at": None,
                "masked": mask_secret(private_store["evm"]["private_key"]),
                "legacy": True,
            }
        )
    if "solana" in private_store:
        secrets_store.append(
            {
                "name": default_secret_name("private", "solana"),
                "type": "private",
                "scope": "solana",
                "created_at": None,
                "masked": mask_secret(private_store["solana"]["private_key"]),
                "legacy": True,
            }
        )
    deduped: dict[str, dict[str, Any]] = {}
    for secret_record in secrets_store:
        deduped[secret_record["name"]] = secret_record
    return sorted(deduped.values(), key=lambda item: item["name"])


def derive_evm_private_key_from_mnemonic(mnemonic: str, index: int = 0) -> str:
    index = normalize_derivation_index(index)
    seed = Bip39SeedGenerator(mnemonic).Generate()
    ctx = (
        Bip44.FromSeed(seed, Bip44Coins.ETHEREUM)
        .Purpose()
        .Coin()
        .Account(0)
        .Change(Bip44Changes.CHAIN_EXT)
        .AddressIndex(index)
    )
    return "0x" + ctx.PrivateKey().Raw().ToHex()


def derive_solana_keypair_from_mnemonic(mnemonic: str, index: int = 0) -> Keypair:
    index = normalize_derivation_index(index)
    seed = Bip39SeedGenerator(mnemonic).Generate()
    ctx = (
        Bip44.FromSeed(seed, Bip44Coins.SOLANA)
        .Purpose()
        .Coin()
        .Account(0)
        .Change(Bip44Changes.CHAIN_EXT)
        .AddressIndex(index)
    )
    return Keypair.from_seed(ctx.PrivateKey().Raw().ToBytes())


def evm_account_from_private_key(private_key: str) -> Any:
    return Account.from_key(private_key)


def solana_keypair_from_private_value(value: str) -> Keypair:
    normalized = value.strip()
    if not normalized:
        raise WalletError("Empty Solana private key")
    if normalized.startswith("["):
        return Keypair.from_json(normalized)
    candidate = Path(normalized).expanduser()
    if candidate.exists():
        return Keypair.from_json(candidate.read_text(encoding="utf-8"))
    return Keypair.from_base58_string(normalized)


def resolve_private_key_slot(chain: str) -> str:
    return "evm" if chain in EVM_CHAINS else "solana"


def resolve_chain_secret(chain: str, source: str = "auto", secret_name: str | None = None) -> tuple[str, str]:
    chain = normalize_chain(chain)
    if secret_name:
        secret_record = find_secret_optional(secret_name)
        if secret_record:
            if source != "auto" and secret_record["type"] != source:
                raise WalletError(
                    f"Secret {secret_name} is a {secret_record['type']} secret, not compatible with requested source {source}"
                )
            if not secret_matches_chain(secret_record, chain):
                raise WalletError(f"Secret {secret_name} is not compatible with {chain}")
            return f"{secret_record['type']}:{secret_record['name']}", secret_record["value"]
        if secret_name == default_secret_name("mnemonic") and MNEMONIC_FILE.exists():
            if source not in ("auto", "mnemonic"):
                raise WalletError(f"Secret {secret_name} is a mnemonic secret, not compatible with requested source {source}")
            return f"mnemonic:{secret_name}", read_text(MNEMONIC_FILE, "mnemonic")
        private_store = load_private_store()
        if secret_name == default_secret_name("private", "ethereum") and "evm" in private_store:
            if source not in ("auto", "private"):
                raise WalletError(f"Secret {secret_name} is a private secret, not compatible with requested source {source}")
            return f"private:{secret_name}", private_store["evm"]["private_key"]
        if secret_name == default_secret_name("private", "solana") and "solana" in private_store:
            if source not in ("auto", "private"):
                raise WalletError(f"Secret {secret_name} is a private secret, not compatible with requested source {source}")
            return f"private:{secret_name}", private_store["solana"]["private_key"]
        raise WalletError(f"Unknown secret: {secret_name}")

    private_store = load_private_store()
    mnemonic_exists = MNEMONIC_FILE.exists()
    slot = resolve_private_key_slot(chain)

    if source == "auto":
        if slot in private_store:
            source = "private"
        elif mnemonic_exists:
            source = "mnemonic"
        else:
            raise WalletError(f"No local secret available for {chain}")

    if source == "private":
        if slot not in private_store:
            raise WalletError(f"No stored private key for {chain}")
        return source, private_store[slot]["private_key"]

    if source == "mnemonic":
        mnemonic = read_text(MNEMONIC_FILE, "mnemonic")
        return source, mnemonic

    raise WalletError(f"Unsupported source: {source}")


def derive_address(chain: str, source: str = "auto", index: int = 0, secret_name: str | None = None) -> tuple[str, str]:
    chain = normalize_chain(chain)
    actual_source, secret = resolve_chain_secret(chain, source, secret_name=secret_name)
    if chain in EVM_CHAINS:
        private_key = secret if actual_source.startswith("private") else derive_evm_private_key_from_mnemonic(secret, index=index)
        return actual_source, evm_account_from_private_key(private_key).address
    keypair = (
        solana_keypair_from_private_value(secret)
        if actual_source.startswith("private")
        else derive_solana_keypair_from_mnemonic(secret, index=index)
    )
    return actual_source, str(keypair.pubkey())


def chains_are_compatible(requested_chain: str, account_chain: str) -> bool:
    requested_chain = normalize_chain(requested_chain)
    account_chain = normalize_chain(account_chain)
    if requested_chain == account_chain:
        return True
    return requested_chain in EVM_CHAINS and account_chain in EVM_CHAINS


def find_account(name: str) -> dict[str, Any]:
    target = normalize_account_name(name)
    for account in load_accounts():
        if account.get("name") == target:
            return account
    raise WalletError(f"Unknown account: {target}")


def get_selected_account(name: str | None, chain: str | None = None) -> dict[str, Any] | None:
    explicit_name = bool(name)
    selected_name = normalize_account_name(name) if explicit_name else load_active_account_name()
    if not selected_name:
        return None
    account = find_account(selected_name)
    if chain and not chains_are_compatible(chain, account.get("chain", "")):
        if not explicit_name:
            return None
        raise WalletError(
            f"Account {selected_name} is for {account.get('chain')}, not compatible with requested chain {normalize_chain(chain)}"
        )
    return account


def derive_account_address(account: dict[str, Any], chain: str | None = None) -> str:
    account_chain = normalize_chain(account["chain"])
    requested_chain = normalize_chain(chain) if chain else account_chain
    if not chains_are_compatible(requested_chain, account_chain):
        raise WalletError(f"Account {account['name']} is not compatible with {requested_chain}")

    source_type = account["source_type"]
    source_name = account.get("source_name")
    derivation_index = int(account.get("derivation_index", 0))
    if source_type == "mnemonic":
        _, address = derive_address(requested_chain, "mnemonic", index=derivation_index, secret_name=source_name)
        return address
    if source_type == "private":
        _, address = derive_address(requested_chain, "private", secret_name=source_name)
        return address
    raise WalletError(f"Unsupported account source: {source_type}")


def resolve_query_target(
    chain: str,
    account_name: str | None,
    explicit_address: str | None,
    source: str,
) -> tuple[str, str, str | None]:
    chain = normalize_chain(chain)
    if explicit_address and account_name:
        raise WalletError("Use either --address or --account, not both")
    if explicit_address:
        return "provided", explicit_address.strip(), None

    account = get_selected_account(account_name, chain)
    if account:
        return f"account:{account['name']}", derive_account_address(account, chain), account["name"]

    source_label, address = derive_address(chain, source)
    return source_label, address, None


def upsert_account(account_record: dict[str, Any]) -> None:
    accounts = load_accounts()
    target_name = account_record["name"]
    for index, existing in enumerate(accounts):
        if existing.get("name") == target_name:
            accounts[index] = account_record
            save_accounts(accounts)
            return
    accounts.append(account_record)
    save_accounts(accounts)


def require_rpc_url(chain: str) -> str:
    env_name = RPC_ENV_VARS[chain]
    rpc_url = os.environ.get(env_name, "").strip()
    if not rpc_url:
        raise WalletError(f"Missing RPC URL. Set {env_name}")
    return rpc_url


def normalize_contract_address(chain: str, contract_address: str) -> str:
    if chain in EVM_CHAINS:
        return Web3.to_checksum_address(contract_address)
    return contract_address.strip()


def load_repo_tokens(chain: str) -> list[dict[str, Any]]:
    raw = read_json(TOKENS_REFERENCE, {})
    target_name = TRACKED_TOKEN_CHAINS[chain]
    for item in raw.get("chains", []):
        if item.get("chain") == target_name:
            merged: list[dict[str, Any]] = []
            for key in ("stablecoins", "main_chain_coins"):
                merged.extend(item.get(key, []))
            deduped: dict[str, dict[str, Any]] = {}
            for token in merged:
                normalized = normalize_contract_address(chain, token["contract_address"])
                deduped[normalized.lower()] = {
                    "chain": chain,
                    "name": token["name"],
                    "symbol": token["symbol"],
                    "decimals": int(token["decimals"]),
                    "contract_address": normalized,
                    "source": "main_tokens",
                }
            return list(deduped.values())
    raise WalletError(f"No tracked token config found for {chain}")


def load_cached_tokens(chain: str) -> list[dict[str, Any]]:
    cached: list[dict[str, Any]] = []
    for token in load_local_tokens():
        try:
            token_chain = normalize_chain(token.get("chain", ""))
        except WalletError:
            continue
        if token_chain != chain:
            continue
        contract_address = token.get("contract_address", "").strip()
        if not contract_address:
            continue
        cached.append(
            {
                "chain": chain,
                "name": token.get("name", "").strip(),
                "symbol": token.get("symbol", "").strip(),
                "decimals": int(token.get("decimals", 0)),
                "contract_address": normalize_contract_address(chain, contract_address),
                "source": "local_cache",
                "discovered_at": token.get("discovered_at", ""),
            }
        )
    return cached


def load_tracked_tokens(chain: str) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for token in load_repo_tokens(chain):
        deduped[token["contract_address"].lower()] = token
    for token in load_cached_tokens(chain):
        deduped[token["contract_address"].lower()] = token
    return list(deduped.values())


def token_lookup_index(chain: str) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for token in load_tracked_tokens(chain):
        for value in (token["contract_address"], token["symbol"], token["name"]):
            key = value.strip().lower()
            if not key:
                continue
            index.setdefault(key, []).append(token)
    return index


def resolve_token_reference(chain: str, token_ref: str) -> tuple[str, dict[str, Any] | None]:
    token_ref = token_ref.strip()
    if not token_ref:
        raise WalletError("Token is required")
    if Web3.is_address(token_ref):
        checksum = normalize_contract_address(chain, token_ref)
        for token in load_tracked_tokens(chain):
            if token["contract_address"].lower() == checksum.lower():
                return checksum, token
        return checksum, None

    matches = token_lookup_index(chain).get(token_ref.lower(), [])
    if not matches:
        raise WalletError(f"Unknown token reference: {token_ref}. Use a token address or query it once first.")
    unique = {token["contract_address"].lower(): token for token in matches}
    if len(unique) > 1:
        raise WalletError(f"Ambiguous token reference: {token_ref}. Use the token address instead.")
    token = next(iter(unique.values()))
    return token["contract_address"], token


def remember_token(chain: str, token_address: str, metadata: dict[str, Any]) -> dict[str, Any]:
    checksum = normalize_contract_address(chain, token_address)
    repo_addresses = {token["contract_address"].lower() for token in load_repo_tokens(chain)}
    if checksum.lower() in repo_addresses:
        return {
            "stored": False,
            "source": "main_tokens",
            "path": str(TOKENS_FILE),
            "contract_address": checksum,
        }

    tokens = load_local_tokens()
    record = {
        "chain": chain,
        "name": metadata["name"],
        "symbol": metadata["symbol"],
        "decimals": int(metadata["decimals"]),
        "contract_address": checksum,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
    }
    replaced = False
    for index, existing in enumerate(tokens):
        existing_chain = existing.get("chain", "").strip().lower()
        existing_address = existing.get("contract_address", "").strip().lower()
        if existing_chain == chain and existing_address == checksum.lower():
            discovered_at = existing.get("discovered_at") or record["discovered_at"]
            tokens[index] = {**record, "discovered_at": discovered_at}
            replaced = True
            break
    if not replaced:
        tokens.append(record)
    save_local_tokens(tokens)
    return {
        "stored": True,
        "source": "local_cache",
        "path": str(TOKENS_FILE),
        "contract_address": checksum,
    }


def rpc_post(url: str, method: str, params: list[Any]) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    request = Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise WalletError(f"RPC HTTP error: {exc.code} {detail}") from exc
    except URLError as exc:
        raise WalletError(f"RPC connection error: {exc.reason}") from exc
    data = json.loads(body)
    if data.get("error"):
        raise WalletError(f"RPC error: {data['error']}")
    return data["result"]


def get_evm_web3(chain: str) -> Web3:
    rpc_url = require_rpc_url(chain)
    web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
    if not web3.is_connected():
        raise WalletError(f"Unable to connect to {chain} RPC")
    return web3


def require_evm_chain(chain: str, action: str) -> str:
    chain = normalize_chain(chain)
    if chain not in EVM_CHAINS:
        raise WalletError(f"{action} is only supported on bsc, base, or ethereum")
    return chain


def get_evm_token_contract(chain: str, token_address: str) -> tuple[Web3, Any, str]:
    chain = require_evm_chain(chain, "ERC-20 operations")
    web3 = get_evm_web3(chain)
    checksum_token = Web3.to_checksum_address(token_address)
    contract = web3.eth.contract(address=checksum_token, abi=ERC20_ABI)
    return web3, contract, checksum_token


def load_evm_token_metadata(contract: Any) -> dict[str, Any]:
    return {
        "name": contract.functions.name().call(),
        "symbol": contract.functions.symbol().call(),
        "decimals": int(contract.functions.decimals().call()),
    }


def parse_token_amount(amount: str, decimals: int) -> tuple[str, int]:
    human = amount.strip()
    if not human:
        raise WalletError("Amount is required")
    scaled = Decimal(human) * (Decimal(10) ** decimals)
    integral = scaled.to_integral_value()
    if scaled != integral:
        raise WalletError(f"Amount has more than {decimals} decimal places")
    raw_amount = int(integral)
    if raw_amount <= 0:
        raise WalletError("Amount must be greater than zero")
    return human, raw_amount


def build_and_send_evm_transaction(
    chain: str,
    contract_call: Any,
    private_key: str,
    from_address: str,
) -> dict[str, Any]:
    web3 = get_evm_web3(chain)
    nonce = web3.eth.get_transaction_count(from_address)
    tx = contract_call.build_transaction(
        {
            "from": from_address,
            "chainId": web3.eth.chain_id,
            "nonce": nonce,
            "gasPrice": web3.eth.gas_price,
        }
    )
    estimated_gas = web3.eth.estimate_gas(tx)
    tx["gas"] = max(int(estimated_gas * 1.2), estimated_gas + 30000)
    signed = web3.eth.account.sign_transaction(tx, private_key=private_key)
    tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
    receipt_status = receipt.get("status") if isinstance(receipt, dict) else receipt.status
    if receipt_status != 1:
        raise WalletError("Transaction reverted on chain")
    return {
        "txHash": tx_hash.hex(),
        "blockNumber": receipt.get("blockNumber") if isinstance(receipt, dict) else receipt.blockNumber,
        "gasUsed": receipt.get("gasUsed") if isinstance(receipt, dict) else receipt.gasUsed,
    }


def query_evm_balances(chain: str, address: str) -> dict[str, Any]:
    web3 = get_evm_web3(chain)
    checksum_address = Web3.to_checksum_address(address)
    assets: list[dict[str, Any]] = []

    native_raw = web3.eth.get_balance(checksum_address)
    if native_raw > 0:
        native_meta = NATIVE_ASSETS[chain]
        assets.append(
            {
                "type": "native",
                "name": native_meta["name"],
                "symbol": native_meta["symbol"],
                "decimals": native_meta["decimals"],
                "raw_balance": str(native_raw),
                "balance": format_units(native_raw, native_meta["decimals"]),
            }
        )

    for token in load_tracked_tokens(chain):
        contract = web3.eth.contract(
            address=Web3.to_checksum_address(token["contract_address"]),
            abi=ERC20_ABI,
        )
        raw_balance = contract.functions.balanceOf(checksum_address).call()
        if raw_balance <= 0:
            continue
        assets.append(
            {
                "type": "token",
                "name": token["name"],
                "symbol": token["symbol"],
                "decimals": token["decimals"],
                "contract_address": token["contract_address"],
                "raw_balance": str(raw_balance),
                "balance": format_units(raw_balance, int(token["decimals"])),
            }
        )

    return {"chain": chain, "address": checksum_address, "assets": assets}


def query_solana_balances(address: str) -> dict[str, Any]:
    rpc_url = require_rpc_url("solana")
    native_result = rpc_post(rpc_url, "getBalance", [address])
    token_result = rpc_post(
        rpc_url,
        "getTokenAccountsByOwner",
        [address, {"programId": SOLANA_TOKEN_PROGRAM}, {"encoding": "jsonParsed"}],
    )

    assets: list[dict[str, Any]] = []
    native_raw = int(native_result["value"])
    if native_raw > 0:
        native_meta = NATIVE_ASSETS["solana"]
        assets.append(
            {
                "type": "native",
                "name": native_meta["name"],
                "symbol": native_meta["symbol"],
                "decimals": native_meta["decimals"],
                "raw_balance": str(native_raw),
                "balance": format_units(native_raw, native_meta["decimals"]),
            }
        )

    mint_balances: dict[str, dict[str, Any]] = {}
    for entry in token_result.get("value", []):
        parsed = entry.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
        token_amount = parsed.get("tokenAmount", {})
        raw_amount = int(token_amount.get("amount", "0"))
        if raw_amount <= 0:
            continue
        mint_balances[parsed.get("mint", "")] = {
            "raw_balance": str(raw_amount),
            "balance": token_amount.get("uiAmountString") or format_units(raw_amount, int(token_amount.get("decimals", 0))),
        }

    for token in load_tracked_tokens("solana"):
        contract_address = token["contract_address"]
        if contract_address not in mint_balances:
            continue
        balance_info = mint_balances[contract_address]
        assets.append(
            {
                "type": "token",
                "name": token["name"],
                "symbol": token["symbol"],
                "decimals": token["decimals"],
                "contract_address": contract_address,
                "raw_balance": balance_info["raw_balance"],
                "balance": balance_info["balance"],
            }
        )

    return {"chain": "solana", "address": address, "assets": assets}


def resolve_evm_private_key(
    source: str = "auto",
    index: int = 0,
    secret_name: str | None = None,
) -> tuple[str, str, str]:
    actual_source, secret = resolve_chain_secret("ethereum", source, secret_name=secret_name)
    private_key = secret if actual_source.startswith("private") else derive_evm_private_key_from_mnemonic(secret, index=index)
    account = evm_account_from_private_key(private_key)
    return actual_source, private_key, account.address


def resolve_evm_signer(
    chain: str,
    account_name: str | None,
    source: str,
) -> tuple[str, str, str, str | None]:
    chain = require_evm_chain(chain, "ERC-20 operations")
    account = get_selected_account(account_name, chain)
    if account:
        if account["source_type"] == "mnemonic":
            derivation_index = int(account.get("derivation_index", 0))
            _, private_key, address = resolve_evm_private_key(
                "mnemonic",
                index=derivation_index,
                secret_name=account.get("source_name"),
            )
        elif account["source_type"] == "private":
            _, private_key, address = resolve_evm_private_key("private", secret_name=account.get("source_name"))
        else:
            raise WalletError(f"Unsupported account source: {account['source_type']}")
        return f"account:{account['name']}", private_key, address, account["name"]

    source_label, private_key, address = resolve_evm_private_key(source)
    return source_label, private_key, address, None


def query_evm_token(
    chain: str,
    token_ref: str,
    holder_address: str | None,
    owner_address: str | None,
    spender_address: str | None,
    account_name: str | None,
    source: str,
) -> dict[str, Any]:
    checksum_token, known_token = resolve_token_reference(chain, token_ref)
    web3, contract, checksum_token = get_evm_token_contract(chain, checksum_token)
    metadata = load_evm_token_metadata(contract)
    raw_total_supply = contract.functions.totalSupply().call()
    registry = remember_token(chain, checksum_token, metadata)
    result: dict[str, Any] = {
        "chain": chain,
        "token_address": checksum_token,
        "name": metadata["name"],
        "symbol": metadata["symbol"],
        "decimals": metadata["decimals"],
        "total_supply": {
            "raw": str(raw_total_supply),
            "formatted": format_units(raw_total_supply, metadata["decimals"]),
        },
        "registry": {
            **registry,
            "resolved_from": known_token["source"] if known_token else "address",
        },
    }

    if holder_address:
        holder = Web3.to_checksum_address(holder_address)
        raw_balance = contract.functions.balanceOf(holder).call()
        result["holder"] = holder
        result["balance"] = {
            "raw": str(raw_balance),
            "formatted": format_units(raw_balance, metadata["decimals"]),
        }
    else:
        try:
            source_label, derived, selected_account = resolve_query_target(chain, account_name, None, source)
        except WalletError:
            if source != "auto" or account_name:
                raise
        else:
            holder = Web3.to_checksum_address(derived)
            raw_balance = contract.functions.balanceOf(holder).call()
            result["holder"] = holder
            result["balance"] = {
                "raw": str(raw_balance),
                "formatted": format_units(raw_balance, metadata["decimals"]),
            }
            result["holder_source"] = source_label
            if selected_account:
                result["account"] = selected_account

    if owner_address or spender_address:
        if not (owner_address and spender_address):
            raise WalletError("Provide both --owner and --spender to query allowance")
        owner = Web3.to_checksum_address(owner_address)
        spender = Web3.to_checksum_address(spender_address)
        raw_allowance = contract.functions.allowance(owner, spender).call()
        result["allowance"] = {
            "owner": owner,
            "spender": spender,
            "raw": str(raw_allowance),
            "formatted": format_units(raw_allowance, metadata["decimals"]),
        }

    return result


def approve_evm_token(
    chain: str,
    token_ref: str,
    spender_address: str,
    amount: str,
    account_name: str | None,
    source: str,
) -> dict[str, Any]:
    checksum_token, _ = resolve_token_reference(chain, token_ref)
    _, contract, checksum_token = get_evm_token_contract(chain, checksum_token)
    metadata = load_evm_token_metadata(contract)
    actual_source, private_key, owner, selected_account = resolve_evm_signer(chain, account_name, source)
    spender = Web3.to_checksum_address(spender_address)
    human_amount, raw_amount = parse_token_amount(amount, metadata["decimals"])
    tx_result = build_and_send_evm_transaction(
        chain,
        contract.functions.approve(spender, raw_amount),
        private_key,
        owner,
    )
    return {
        "chain": chain,
        "source": actual_source,
        "owner": owner,
        "spender": spender,
        "account": selected_account,
        "token_address": checksum_token,
        "symbol": metadata["symbol"],
        "decimals": metadata["decimals"],
        "amount": {"input": human_amount, "raw": str(raw_amount)},
        **tx_result,
    }


def transfer_evm_token(
    chain: str,
    token_ref: str,
    to_address: str,
    amount: str,
    account_name: str | None,
    source: str,
) -> dict[str, Any]:
    checksum_token, _ = resolve_token_reference(chain, token_ref)
    _, contract, checksum_token = get_evm_token_contract(chain, checksum_token)
    metadata = load_evm_token_metadata(contract)
    actual_source, private_key, sender, selected_account = resolve_evm_signer(chain, account_name, source)
    recipient = Web3.to_checksum_address(to_address)
    human_amount, raw_amount = parse_token_amount(amount, metadata["decimals"])
    tx_result = build_and_send_evm_transaction(
        chain,
        contract.functions.transfer(recipient, raw_amount),
        private_key,
        sender,
    )
    return {
        "chain": chain,
        "source": actual_source,
        "from": sender,
        "to": recipient,
        "account": selected_account,
        "token_address": checksum_token,
        "symbol": metadata["symbol"],
        "decimals": metadata["decimals"],
        "amount": {"input": human_amount, "raw": str(raw_amount)},
        **tx_result,
    }


def cmd_mnemonic_generate(args: argparse.Namespace) -> None:
    mnemonic = generate_mnemonic()
    secret_name = normalize_secret_name(args.name) if getattr(args, "name", None) else None
    stored_paths: list[str] = []
    if secret_name:
        secret_record = remember_secret(secret_name, "mnemonic", mnemonic)
        stored_paths.append(str(SECRETS_FILE))
        evm_source_name = secret_record["name"]
    else:
        write_text_secret(MNEMONIC_FILE, mnemonic)
        stored_paths.append(str(MNEMONIC_FILE))
        evm_source_name = None

    _, evm_address = derive_address("ethereum", "mnemonic", secret_name=evm_source_name)
    _, solana_address = derive_address("solana", "mnemonic", secret_name=evm_source_name)
    payload = {
        "status": "ok",
        "stored": stored_paths,
        "mnemonic": {"masked": mask_mnemonic(mnemonic)},
        "addresses": {
            "ethereum": evm_address,
            "bsc": evm_address,
            "base": evm_address,
            "solana": solana_address,
        },
    }
    if secret_name:
        payload["secret"] = {"name": secret_name, "type": "mnemonic"}
    print_json(payload)


def cmd_mnemonic_import(args: argparse.Namespace) -> None:
    mnemonic = validate_mnemonic(read_secret_value(args.value, args.stdin, "mnemonic"))
    secret_name = normalize_secret_name(args.name) if getattr(args, "name", None) else None
    stored_paths: list[str] = []
    if secret_name:
        secret_record = remember_secret(secret_name, "mnemonic", mnemonic)
        stored_paths.append(str(SECRETS_FILE))
        evm_source_name = secret_record["name"]
    else:
        write_text_secret(MNEMONIC_FILE, mnemonic)
        stored_paths.append(str(MNEMONIC_FILE))
        evm_source_name = None

    _, evm_address = derive_address("ethereum", "mnemonic", secret_name=evm_source_name)
    _, solana_address = derive_address("solana", "mnemonic", secret_name=evm_source_name)
    payload = {
        "status": "ok",
        "stored": stored_paths,
        "mnemonic": {"masked": mask_mnemonic(mnemonic)},
        "addresses": {
            "ethereum": evm_address,
            "bsc": evm_address,
            "base": evm_address,
            "solana": solana_address,
        },
    }
    if secret_name:
        payload["secret"] = {"name": secret_name, "type": "mnemonic"}
    print_json(payload)


def cmd_private_generate(args: argparse.Namespace) -> None:
    chain = normalize_chain(args.chain)
    secret_name = normalize_secret_name(args.name) if getattr(args, "name", None) else None
    store = load_private_store()
    if chain in EVM_CHAINS:
        private_key = "0x" + secrets.token_hex(32)
        account = evm_account_from_private_key(private_key)
        stored_paths: list[str] = []
        if secret_name:
            remember_secret(secret_name, "private", private_key, chain=chain)
            stored_paths.append(str(SECRETS_FILE))
        else:
            store["evm"] = {"private_key": private_key}
            save_private_store(store)
            stored_paths.append(str(PRIVATE_FILE))
        payload = {
            "status": "ok",
            "chain": chain,
            "stored": stored_paths,
            "private_key": {"masked": mask_secret(private_key)},
            "address": account.address,
        }
        if secret_name:
            payload["secret"] = {"name": secret_name, "type": "private", "scope": "evm"}
        print_json(payload)
        return

    keypair = Keypair()
    private_key = str(keypair)
    stored_paths: list[str] = []
    if secret_name:
        remember_secret(secret_name, "private", private_key, chain=chain)
        stored_paths.append(str(SECRETS_FILE))
    else:
        store["solana"] = {"private_key": private_key}
        save_private_store(store)
        stored_paths.append(str(PRIVATE_FILE))
    payload = {
        "status": "ok",
        "chain": chain,
        "stored": stored_paths,
        "private_key": {"masked": mask_secret(private_key)},
        "address": str(keypair.pubkey()),
    }
    if secret_name:
        payload["secret"] = {"name": secret_name, "type": "private", "scope": "solana"}
    print_json(payload)


def cmd_private_import(args: argparse.Namespace) -> None:
    chain = normalize_chain(args.chain)
    raw_value = read_secret_value(args.value, args.stdin, "private key")
    secret_name = normalize_secret_name(args.name) if getattr(args, "name", None) else None
    store = load_private_store()

    if chain in EVM_CHAINS:
        private_key = raw_value if raw_value.startswith("0x") else f"0x{raw_value}"
        account = evm_account_from_private_key(private_key)
        stored_paths: list[str] = []
        if secret_name:
            remember_secret(secret_name, "private", private_key, chain=chain)
            stored_paths.append(str(SECRETS_FILE))
        else:
            store["evm"] = {"private_key": private_key}
            save_private_store(store)
            stored_paths.append(str(PRIVATE_FILE))
        payload = {
            "status": "ok",
            "chain": chain,
            "stored": stored_paths,
            "private_key": {"masked": mask_secret(private_key)},
            "address": account.address,
        }
        if secret_name:
            payload["secret"] = {"name": secret_name, "type": "private", "scope": "evm"}
        print_json(payload)
        return

    keypair = solana_keypair_from_private_value(raw_value)
    private_key = str(keypair)
    stored_paths: list[str] = []
    if secret_name:
        remember_secret(secret_name, "private", private_key, chain=chain)
        stored_paths.append(str(SECRETS_FILE))
    else:
        store["solana"] = {"private_key": private_key}
        save_private_store(store)
        stored_paths.append(str(PRIVATE_FILE))
    payload = {
        "status": "ok",
        "chain": chain,
        "stored": stored_paths,
        "private_key": {"masked": mask_secret(private_key)},
        "address": str(keypair.pubkey()),
    }
    if secret_name:
        payload["secret"] = {"name": secret_name, "type": "private", "scope": "solana"}
    print_json(payload)


def cmd_secret_list(_: argparse.Namespace) -> None:
    print_json({"status": "ok", "stored": str(SECRETS_FILE), "secrets": list_secrets_with_legacy()})


def cmd_secret_show(args: argparse.Namespace) -> None:
    secret_record = find_secret_optional(args.name)
    if secret_record:
        print_json({"status": "ok", "secret": secret_summary(secret_record), "stored": str(SECRETS_FILE)})
        return

    legacy_name = normalize_secret_name(args.name)
    if legacy_name == default_secret_name("mnemonic") and MNEMONIC_FILE.exists():
        mnemonic = read_text(MNEMONIC_FILE, "mnemonic")
        print_json(
            {
                "status": "ok",
                "secret": {
                    "name": legacy_name,
                    "type": "mnemonic",
                    "scope": "all",
                    "legacy": True,
                    "masked": mask_mnemonic(mnemonic),
                },
            }
        )
        return
    if legacy_name == default_secret_name("private", "ethereum"):
        private_store = load_private_store()
        if "evm" in private_store:
            print_json(
                {
                    "status": "ok",
                    "secret": {
                        "name": legacy_name,
                        "type": "private",
                        "scope": "evm",
                        "legacy": True,
                        "masked": mask_secret(private_store["evm"]["private_key"]),
                    },
                }
            )
            return
    if legacy_name == default_secret_name("private", "solana"):
        private_store = load_private_store()
        if "solana" in private_store:
            print_json(
                {
                    "status": "ok",
                    "secret": {
                        "name": legacy_name,
                        "type": "private",
                        "scope": "solana",
                        "legacy": True,
                        "masked": mask_secret(private_store["solana"]["private_key"]),
                    },
                }
            )
            return
    raise WalletError(f"Unknown secret: {args.name}")


def cmd_account_add(args: argparse.Namespace) -> None:
    chain = normalize_chain(args.chain)
    name = normalize_account_name(args.name)
    derivation_index = normalize_derivation_index(args.index)
    source_type = args.source
    source_name = normalize_secret_name(args.source_name) if args.source_name else None

    if source_type == "mnemonic":
        if source_name:
            _, address = derive_address(chain, "mnemonic", index=derivation_index, secret_name=source_name)
        else:
            if not MNEMONIC_FILE.exists():
                raise WalletError(f"Missing mnemonic: {MNEMONIC_FILE}")
            _, address = derive_address(chain, "mnemonic", index=derivation_index)
    elif source_type == "private":
        if source_name:
            _, address = derive_address(chain, "private", secret_name=source_name)
        else:
            _, address = derive_address(chain, "private")
        derivation_index = 0
    else:
        raise WalletError(f"Unsupported account source: {source_type}")

    record = {
        "name": name,
        "chain": chain,
        "source_type": source_type,
        "source_name": source_name or default_secret_name(source_type, chain),
        "derivation_index": derivation_index,
        "address": address,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    upsert_account(record)

    activated = False
    if args.use or load_active_account_name() is None:
        save_active_account_name(name)
        activated = True

    print_json(
        {
            "status": "ok",
            "account": record,
            "stored": str(ACCOUNTS_FILE),
            "active": activated,
            "active_file": str(ACTIVE_ACCOUNT_FILE),
        }
    )


def cmd_account_list(_: argparse.Namespace) -> None:
    active_name = load_active_account_name()
    accounts: list[dict[str, Any]] = []
    for account in sorted(load_accounts(), key=lambda item: item.get("name", "")):
        entry = dict(account)
        entry["active"] = account.get("name") == active_name
        accounts.append(entry)
    print_json({"status": "ok", "active_account": active_name, "accounts": accounts})


def cmd_account_show(args: argparse.Namespace) -> None:
    account = get_selected_account(args.name)
    if not account:
        raise WalletError("No active account selected")
    print_json({"status": "ok", "active_account": load_active_account_name(), "account": account})


def cmd_account_use(args: argparse.Namespace) -> None:
    account = find_account(args.name)
    save_active_account_name(account["name"])
    print_json({"status": "ok", "active_account": account["name"], "stored": str(ACTIVE_ACCOUNT_FILE)})


def cmd_address_show(args: argparse.Namespace) -> None:
    chain = normalize_chain(args.chain)
    account = get_selected_account(args.account, chain)
    if account:
        source = f"account:{account['name']}"
        address = derive_account_address(account, chain)
        print_json(
            {
                "status": "ok",
                "chain": chain,
                "source": source,
                "account": account["name"],
                "address": address,
            }
        )
        return

    source, address = derive_address(chain, args.source)
    print_json({"status": "ok", "chain": chain, "source": source, "address": address})


def cmd_balances(args: argparse.Namespace) -> None:
    chain = normalize_chain(args.chain)
    source, address, account_name = resolve_query_target(chain, args.account, args.address, args.source)

    result = query_solana_balances(address) if chain == "solana" else query_evm_balances(chain, address)
    result["status"] = "ok"
    result["source"] = source
    if account_name:
        result["account"] = account_name
    print_json(result)


def cmd_token_query(args: argparse.Namespace) -> None:
    result = query_evm_token(
        chain=normalize_chain(args.chain),
        token_ref=args.token,
        holder_address=args.address,
        owner_address=args.owner,
        spender_address=args.spender,
        account_name=args.account,
        source=args.source,
    )
    result["status"] = "ok"
    print_json(result)


def cmd_token_approve(args: argparse.Namespace) -> None:
    result = approve_evm_token(
        chain=normalize_chain(args.chain),
        token_ref=args.token,
        spender_address=args.spender,
        amount=args.amount,
        account_name=args.account,
        source=args.source,
    )
    print_json({"status": "ok", "approval": result})


def cmd_token_transfer(args: argparse.Namespace) -> None:
    result = transfer_evm_token(
        chain=normalize_chain(args.chain),
        token_ref=args.token,
        to_address=args.to,
        amount=args.amount,
        account_name=args.account,
        source=args.source,
    )
    print_json({"status": "ok", "transfer": result})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage a local UXUY Web3 wallet")
    subparsers = parser.add_subparsers(dest="command", required=True)

    mnemonic_parser = subparsers.add_parser("mnemonic", help="Generate or import a mnemonic")
    mnemonic_subparsers = mnemonic_parser.add_subparsers(dest="mnemonic_command", required=True)

    mnemonic_generate = mnemonic_subparsers.add_parser("generate", help="Generate and store a mnemonic")
    mnemonic_generate.add_argument("--name", help="Store as a named secret in .secrets instead of the legacy .mnemonic file")
    mnemonic_generate.set_defaults(func=cmd_mnemonic_generate)

    mnemonic_import = mnemonic_subparsers.add_parser("import", help="Import and store a mnemonic")
    mnemonic_import.add_argument("--name", help="Store as a named secret in .secrets instead of the legacy .mnemonic file")
    mnemonic_import.add_argument("--value", help="Mnemonic value")
    mnemonic_import.add_argument("--stdin", action="store_true", help="Read mnemonic from stdin")
    mnemonic_import.set_defaults(func=cmd_mnemonic_import)

    private_parser = subparsers.add_parser("private", help="Generate or import a private key")
    private_subparsers = private_parser.add_subparsers(dest="private_command", required=True)

    private_generate = private_subparsers.add_parser("generate", help="Generate and store a private key")
    private_generate.add_argument("--chain", required=True)
    private_generate.add_argument("--name", help="Store as a named secret in .secrets instead of the legacy .private file")
    private_generate.set_defaults(func=cmd_private_generate)

    private_import = private_subparsers.add_parser("import", help="Import and store a private key")
    private_import.add_argument("--chain", required=True)
    private_import.add_argument("--name", help="Store as a named secret in .secrets instead of the legacy .private file")
    private_import.add_argument("--value", help="Private key value")
    private_import.add_argument("--stdin", action="store_true", help="Read private key from stdin")
    private_import.set_defaults(func=cmd_private_import)

    secret_parser = subparsers.add_parser("secret", help="List or inspect named secrets")
    secret_subparsers = secret_parser.add_subparsers(dest="secret_command", required=True)

    secret_list = secret_subparsers.add_parser("list", help="List named secrets and legacy defaults")
    secret_list.set_defaults(func=cmd_secret_list)

    secret_show = secret_subparsers.add_parser("show", help="Show one secret summary")
    secret_show.add_argument("--name", required=True)
    secret_show.set_defaults(func=cmd_secret_show)

    account_parser = subparsers.add_parser("account", help="Create and manage named wallet accounts")
    account_subparsers = account_parser.add_subparsers(dest="account_command", required=True)

    account_add = account_subparsers.add_parser("add", help="Add or update a named account")
    account_add.add_argument("--name", required=True)
    account_add.add_argument("--chain", required=True)
    account_add.add_argument("--source", choices=["mnemonic", "private"], required=True)
    account_add.add_argument("--source-name", help="Named secret to bind this account to. Defaults to the legacy secret slot")
    account_add.add_argument("--index", type=int, default=0, help="Mnemonic derivation index, only used with --source mnemonic")
    account_add.add_argument("--use", action="store_true", help="Set the account as active after saving")
    account_add.set_defaults(func=cmd_account_add)

    account_list = account_subparsers.add_parser("list", help="List saved accounts")
    account_list.set_defaults(func=cmd_account_list)

    account_show = account_subparsers.add_parser("show", help="Show one saved account")
    account_show.add_argument("--name", help="Account name. Defaults to the active account")
    account_show.set_defaults(func=cmd_account_show)

    account_use = account_subparsers.add_parser("use", help="Set the active account")
    account_use.add_argument("--name", required=True)
    account_use.set_defaults(func=cmd_account_use)

    address_parser = subparsers.add_parser("address", help="Show the derived wallet address")
    address_subparsers = address_parser.add_subparsers(dest="address_command", required=True)
    address_show = address_subparsers.add_parser("show", help="Show address for a chain")
    address_show.add_argument("--chain", required=True)
    address_show.add_argument("--account", help="Named account. Defaults to the active account when present")
    address_show.add_argument("--source", choices=["auto", "mnemonic", "private"], default="auto")
    address_show.set_defaults(func=cmd_address_show)

    balances_parser = subparsers.add_parser("balances", help="Query native and tracked token balances")
    balances_parser.add_argument("--chain", required=True)
    balances_parser.add_argument("--address")
    balances_parser.add_argument("--account", help="Named account. Defaults to the active account when present")
    balances_parser.add_argument("--source", choices=["auto", "mnemonic", "private"], default="auto")
    balances_parser.set_defaults(func=cmd_balances)

    token_parser = subparsers.add_parser("token", help="Query or manage ERC-20 tokens")
    token_subparsers = token_parser.add_subparsers(dest="token_command", required=True)

    token_query = token_subparsers.add_parser("query", help="Query standard ERC-20 info, balance, or allowance")
    token_query.add_argument("--chain", required=True)
    token_query.add_argument("--token", required=True, help="Token address or a known symbol/name from main_tokens.json or .tokens")
    token_query.add_argument("--address", help="Holder address for balance query")
    token_query.add_argument("--account", help="Named account. Defaults to the active account when present")
    token_query.add_argument("--owner", help="Allowance owner address")
    token_query.add_argument("--spender", help="Allowance spender address")
    token_query.add_argument("--source", choices=["auto", "mnemonic", "private"], default="auto")
    token_query.set_defaults(func=cmd_token_query)

    token_approve = token_subparsers.add_parser("approve", help="Approve an ERC-20 spender")
    token_approve.add_argument("--chain", required=True)
    token_approve.add_argument("--token", required=True)
    token_approve.add_argument("--account", help="Named account. Defaults to the active account when present")
    token_approve.add_argument("--spender", required=True)
    token_approve.add_argument("--amount", required=True)
    token_approve.add_argument("--source", choices=["auto", "mnemonic", "private"], default="auto")
    token_approve.set_defaults(func=cmd_token_approve)

    token_transfer = token_subparsers.add_parser("transfer", help="Transfer an ERC-20 token")
    token_transfer.add_argument("--chain", required=True)
    token_transfer.add_argument("--token", required=True)
    token_transfer.add_argument("--account", help="Named account. Defaults to the active account when present")
    token_transfer.add_argument("--to", required=True)
    token_transfer.add_argument("--amount", required=True)
    token_transfer.add_argument("--source", choices=["auto", "mnemonic", "private"], default="auto")
    token_transfer.set_defaults(func=cmd_token_transfer)

    return parser


def main() -> int:
    try:
        Account.enable_unaudited_hdwallet_features()
        parser = build_parser()
        args = parser.parse_args()
        args.func(args)
        return 0
    except WalletError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
