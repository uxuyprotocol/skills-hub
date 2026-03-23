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
    TrxAddrEncoder,
)
from eth_account import Account
from solders.keypair import Keypair
from web3 import Web3

getcontext().prec = 78

SCRIPT_DIR = Path(__file__).resolve().parent
TOKENS_REFERENCE = SCRIPT_DIR / "main_tokens.json"
STORAGE_DIR = Path(os.environ.get("UXUY_WALLET_HOME", Path.home() / ".uxuy-wallet")).expanduser()
TOKENS_FILE = STORAGE_DIR / ".tokens"
ACCOUNTS_FILE = STORAGE_DIR / ".accounts"
ACTIVE_ACCOUNT_FILE = STORAGE_DIR / ".active"

EVM_CHAINS = {"bsc", "base", "ethereum"}
TVM_CHAINS = {"tron"}
SUPPORTED_CHAINS = EVM_CHAINS | TVM_CHAINS | {"solana"}
RPC_ENV_VARS = {
    "bsc": "BSC_RPC_URL",
    "base": "BASE_RPC_URL",
    "ethereum": "ETHEREUM_RPC_URL",
    "solana": "SOLANA_RPC_URL",
    "tron": "TRON_RPC_URL",
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
    "tron": {"name": "TRON", "symbol": "TRX", "decimals": 6},
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
    aliases = {"bnb": "bsc", "bnbchain": "bsc", "eth": "ethereum", "trx": "tron"}
    chain = aliases.get(chain, chain)
    if chain not in SUPPORTED_CHAINS:
        raise WalletError(f"Unsupported chain: {value}")
    return chain


def write_json(path: Path, value: Any) -> None:
    ensure_storage_dir()
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)

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


ADDRESS_FAMILIES = {
    "bsc": "evm",
    "base": "evm",
    "ethereum": "evm",
    "solana": "svm",
    "tron": "tvm",
}
SUPPORTED_ADDRESS_FAMILIES = ("evm", "svm", "tvm")
FAMILY_CHAINS = {
    "evm": ["ethereum", "bsc", "base"],
    "svm": ["solana"],
    "tvm": ["tron"],
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_address_family(value: str) -> str:
    family = value.strip().lower()
    if family not in SUPPORTED_ADDRESS_FAMILIES:
        raise WalletError(f"Unsupported address type: {value}")
    return family


def address_family_for_chain(chain: str) -> str:
    normalized_chain = normalize_chain(chain)
    return ADDRESS_FAMILIES[normalized_chain]


def empty_tree_branch() -> dict[str, list[dict[str, Any]]]:
    return {"keys": []}


def empty_root_trees() -> dict[str, dict[str, list[dict[str, Any]]]]:
    return {family: empty_tree_branch() for family in SUPPORTED_ADDRESS_FAMILIES}


def empty_accounts_store() -> dict[str, list[dict[str, Any]]]:
    return {"roots": []}


def secret_payload(value: str, masked: str | None = None) -> dict[str, str]:
    normalized = value.strip()
    return {
        "value": normalized,
        "masked": masked if masked is not None else mask_secret(normalized),
    }


def build_mnemonic_key_node(address_family: str, mnemonic: str, index: int = 0, created_at: str | None = None) -> dict[str, Any]:
    family = normalize_address_family(address_family)
    derivation_index = normalize_derivation_index(index)
    created_at = created_at or utc_now_iso()

    if family == "evm":
        private_key = derive_evm_private_key_from_mnemonic(mnemonic, index=derivation_index)
        address = evm_account_from_private_key(private_key).address
    elif family == "svm":
        keypair = derive_solana_keypair_from_mnemonic(mnemonic, index=derivation_index)
        private_key = str(keypair)
        address = str(keypair.pubkey())
    elif family == "tvm":
        private_key = derive_tron_private_key_from_mnemonic(mnemonic, index=derivation_index)
        address = tron_address_from_private_key(private_key)
    else:
        private_key = ""
        address = ""

    return {
        "name": "",
        "derivation_index": derivation_index,
        "private_key": secret_payload(private_key) if private_key else {},
        "address": address,
        "created_at": created_at,
    }


def build_private_key_node(chain: str, value: str, created_at: str | None = None) -> tuple[str, dict[str, Any]]:
    normalized_chain = normalize_chain(chain)
    family = address_family_for_chain(normalized_chain)
    created_at = created_at or utc_now_iso()

    if family == "evm":
        private_key = value if value.startswith("0x") else f"0x{value}"
        address = evm_account_from_private_key(private_key).address
    elif family == "svm":
        keypair = solana_keypair_from_private_value(value)
        private_key = str(keypair)
        address = str(keypair.pubkey())
    else:
        private_key = value if value.startswith("0x") else f"0x{value}"
        address = tron_address_from_private_key(private_key)

    return family, {
        "name": "",
        "derivation_index": 0,
        "private_key": secret_payload(private_key),
        "address": address,
        "created_at": created_at,
    }


def normalize_key_node(node: dict[str, Any], family: str) -> dict[str, Any]:
    if not isinstance(node, dict):
        raise WalletError(f"Invalid tree key format: {ACCOUNTS_FILE}")
    private_key = node.get("private_key", {})
    if private_key is None:
        private_key = {}
    if not isinstance(private_key, dict):
        raise WalletError(f"Invalid private_key payload in {ACCOUNTS_FILE}")
    key_name = str(node.get("name", "")).strip()
    key_created_at = node.get("created_at")
    legacy_accounts = node.get("accounts", [])
    if legacy_accounts is None:
        legacy_accounts = []
    if not isinstance(legacy_accounts, list):
        raise WalletError(f"Invalid account leaf list in {ACCOUNTS_FILE}")
    if not key_name:
        for account in legacy_accounts:
            if not isinstance(account, dict):
                raise WalletError(f"Invalid account leaf format: {ACCOUNTS_FILE}")
            legacy_name = str(account.get("name", "")).strip()
            if legacy_name:
                key_name = normalize_account_name(legacy_name)
                key_created_at = account.get("created_at") or key_created_at
                break
    return {
        "name": normalize_account_name(key_name) if key_name else "",
        "derivation_index": int(node.get("derivation_index", 0)),
        "private_key": {
            "value": str(private_key.get("value", "")).strip(),
            "masked": str(private_key.get("masked", "")).strip(),
        },
        "address": str(node.get("address", "")).strip(),
        "created_at": key_created_at,
    }


def normalize_root_record(root: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(root, dict):
        raise WalletError(f"Invalid root format: {ACCOUNTS_FILE}")
    kind = str(root.get("kind", "")).strip()
    if kind not in {"mnemonic", "private"}:
        raise WalletError(f"Invalid root kind in {ACCOUNTS_FILE}: {kind}")
    name = normalize_mnemonic_name(str(root.get("name", ""))) if kind == "mnemonic" else normalize_account_name(
        str(root.get("name", ""))
    )
    if kind == "private":
        private_key = root.get("private_key", {})
        if private_key is None:
            private_key = {}
        if not isinstance(private_key, dict):
            raise WalletError(f"Invalid private key payload in {ACCOUNTS_FILE}")

        address_type = str(root.get("address_type", "")).strip()
        address = str(root.get("address", "")).strip()

        if not (address_type and private_key.get("value") and address):
            chain = str(root.get("chain", "")).strip()
            family = str(root.get("family", "")).strip()
            legacy_family = normalize_address_family(family) if family else (
                address_family_for_chain(chain) if chain else ""
            )
            secret = root.get("secret", {})
            if secret is None:
                secret = {}
            if not isinstance(secret, dict):
                raise WalletError(f"Invalid secret payload in {ACCOUNTS_FILE}")
            raw_trees = root.get("trees", {})
            if raw_trees is None:
                raw_trees = {}
            if not isinstance(raw_trees, dict):
                raise WalletError(f"Invalid tree payload in {ACCOUNTS_FILE}")
            legacy_key: dict[str, Any] | None = None
            if legacy_family:
                branch = raw_trees.get(legacy_family, {})
                if branch is None:
                    branch = {}
                if not isinstance(branch, dict):
                    raise WalletError(f"Invalid {legacy_family} branch in {ACCOUNTS_FILE}")
                keys = branch.get("keys", [])
                if not isinstance(keys, list):
                    raise WalletError(f"Invalid key list in {ACCOUNTS_FILE}::{legacy_family}")
                if keys:
                    legacy_key = normalize_key_node(keys[0], legacy_family)
            address_type = address_type or legacy_family
            if legacy_key is not None:
                private_key = private_key if private_key.get("value") else legacy_key.get("private_key", {})
                address = address or str(legacy_key.get("address", "")).strip()

            if not private_key.get("value") and isinstance(secret, dict):
                private_key = {
                    "value": str(secret.get("value", "")).strip(),
                    "masked": str(secret.get("masked", "")).strip(),
                }

        return {
            "kind": "private",
            "name": name,
            "created_at": root.get("created_at"),
            "address_type": normalize_address_family(address_type),
            "private_key": {
                "value": str(private_key.get("value", "")).strip(),
                "masked": str(private_key.get("masked", "")).strip(),
            },
            "address": address,
        }

    secret = root.get("secret", {})
    if secret is None:
        secret = {}
    if not isinstance(secret, dict):
        raise WalletError(f"Invalid secret payload in {ACCOUNTS_FILE}")

    trees = empty_root_trees()
    raw_trees = root.get("trees", {})
    if raw_trees is None:
        raw_trees = {}
    if not isinstance(raw_trees, dict):
        raise WalletError(f"Invalid tree payload in {ACCOUNTS_FILE}")
    for family in SUPPORTED_ADDRESS_FAMILIES:
        branch = raw_trees.get(family, {})
        if branch is None:
            branch = {}
        if not isinstance(branch, dict):
            raise WalletError(f"Invalid {family} branch in {ACCOUNTS_FILE}")
        keys = branch.get("keys", [])
        if not isinstance(keys, list):
            raise WalletError(f"Invalid key list in {ACCOUNTS_FILE}::{family}")
        trees[family] = {"keys": [normalize_key_node(node, family) for node in keys]}

    return {
        "kind": kind,
        "name": name,
        "created_at": root.get("created_at"),
        "secret": {
            "value": str(secret.get("value", "")).strip(),
            "masked": str(secret.get("masked", "")).strip(),
        },
        "trees": trees,
    }


def normalize_accounts_store(raw: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(raw, dict):
        raise WalletError(f"Invalid accounts format: {ACCOUNTS_FILE}")
    roots = raw.get("roots", [])
    if not isinstance(roots, list):
        raise WalletError(f"Invalid roots format: {ACCOUNTS_FILE}")
    return {"roots": [normalize_root_record(root) for root in roots]}


def build_mnemonic_root_record(name: str, value: str, created_at: str | None = None) -> dict[str, Any]:
    created_at = created_at or utc_now_iso()
    mnemonic = validate_mnemonic(value)
    root = {
        "kind": "mnemonic",
        "name": normalize_mnemonic_name(name),
        "created_at": created_at,
        "secret": {
            "value": mnemonic,
            "masked": mask_mnemonic(mnemonic),
        },
        "trees": empty_root_trees(),
    }
    root["trees"]["evm"]["keys"].append(build_mnemonic_key_node("evm", mnemonic, index=0, created_at=created_at))
    root["trees"]["svm"]["keys"].append(build_mnemonic_key_node("svm", mnemonic, index=0, created_at=created_at))
    root["trees"]["tvm"]["keys"].append(build_mnemonic_key_node("tvm", mnemonic, index=0, created_at=created_at))
    return root


def build_private_root_record(name: str, chain: str, value: str, created_at: str | None = None) -> dict[str, Any]:
    created_at = created_at or utc_now_iso()
    normalized_name = normalize_account_name(name)
    normalized_chain = normalize_chain(chain)
    family, key_node = build_private_key_node(normalized_chain, value, created_at=created_at)
    return {
        "kind": "private",
        "name": normalized_name,
        "created_at": created_at,
        "address_type": family,
        "private_key": key_node["private_key"],
        "address": key_node["address"],
    }


def find_root_in_store(store: dict[str, list[dict[str, Any]]], kind: str, name: str) -> tuple[int | None, dict[str, Any] | None]:
    normalized_name = normalize_mnemonic_name(name) if kind == "mnemonic" else normalize_account_name(name)
    for index, root in enumerate(store["roots"]):
        if root.get("kind") == kind and root.get("name") == normalized_name:
            return index, root
    return None, None


def account_tree_path(account_record: dict[str, Any]) -> str:
    family = account_address_family(account_record)
    if account_record.get("source_type") == "mnemonic":
        return (
            f"mnemonic:{account_record['mnemonic_name']}/"
            f"{family}/index:{int(account_record.get('derivation_index', 0))}"
        )
    root_name = account_record.get("root_name") or account_record["name"]
    return f"private:{root_name}/{family}"


def root_branch_summary(root: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    branches: dict[str, list[dict[str, Any]]] = {}
    for family in SUPPORTED_ADDRESS_FAMILIES:
        items: list[dict[str, Any]] = []
        keys = sorted(root["trees"][family]["keys"], key=lambda item: int(item.get("derivation_index", 0)))
        for key in keys:
            items.append(
                {
                    "name": key.get("name") or None,
                    "derivation_index": int(key.get("derivation_index", 0)),
                    "masked_private_key": key.get("private_key", {}).get("masked") or None,
                    "address": key.get("address") or None,
                }
            )
        branches[family] = items
    return branches


def flatten_mnemonic_root(root: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": root["name"],
        "value": root.get("secret", {}).get("value", ""),
        "masked": root.get("secret", {}).get("masked", ""),
        "created_at": root.get("created_at"),
        "branches": root_branch_summary(root),
    }


def find_or_create_key_node(root: dict[str, Any], family: str, derivation_index: int = 0, created_at: str | None = None) -> dict[str, Any]:
    address_family = normalize_address_family(family)
    index = normalize_derivation_index(derivation_index)
    if root["kind"] == "private":
        raise WalletError("Private roots do not support derived key branches")

    branch = root["trees"][address_family]
    for key in branch["keys"]:
        if int(key.get("derivation_index", 0)) == index:
            return key

    if root.get("secret", {}).get("value"):
        key_node = build_mnemonic_key_node(
            address_family,
            root["secret"]["value"],
            index=index,
            created_at=created_at or root.get("created_at"),
        )
    else:
        key_node = {
            "name": "",
            "derivation_index": index,
            "private_key": {},
            "address": "",
            "created_at": created_at or root.get("created_at"),
        }
    branch["keys"].append(key_node)
    return key_node


def assign_key_name(key_node: dict[str, Any], name: str, created_at: str | None = None) -> None:
    key_node["name"] = normalize_account_name(name)
    key_node["created_at"] = created_at or key_node.get("created_at") or utc_now_iso()


def prune_empty_private_roots(store: dict[str, list[dict[str, Any]]]) -> None:
    retained: list[dict[str, Any]] = []
    for root in store["roots"]:
        if root.get("kind") != "private":
            retained.append(root)
            continue
        if root.get("name"):
            retained.append(root)
    store["roots"] = retained


def remove_account_name_from_store(store: dict[str, list[dict[str, Any]]], name: str) -> None:
    target_name = normalize_account_name(name)
    retained: list[dict[str, Any]] = []
    for root in store["roots"]:
        if root.get("kind") == "private" and root.get("name") == target_name:
            continue
        for family in SUPPORTED_ADDRESS_FAMILIES:
            for key in root.get("trees", {}).get(family, {}).get("keys", []):
                if key.get("name") == target_name:
                    key["name"] = ""
        retained.append(root)
    store["roots"] = retained
    prune_empty_private_roots(store)


def merge_mnemonic_root(existing: dict[str, Any], value: str, created_at: str | None = None) -> dict[str, Any]:
    root = build_mnemonic_root_record(existing["name"], value, created_at=created_at or utc_now_iso())
    for family in SUPPORTED_ADDRESS_FAMILIES:
        for key in existing["trees"][family]["keys"]:
            derivation_index = int(key.get("derivation_index", 0))
            target = find_or_create_key_node(root, family, derivation_index, created_at=key.get("created_at") or root.get("created_at"))
            if not target.get("address") and key.get("address"):
                target["address"] = key["address"]
            if not target.get("private_key") and key.get("private_key"):
                target["private_key"] = key["private_key"]
            if key.get("name") and not target.get("name"):
                target["name"] = key["name"]
                target["created_at"] = key.get("created_at") or target.get("created_at")
    return root


def load_accounts_store() -> dict[str, list[dict[str, Any]]]:
    raw = read_json(ACCOUNTS_FILE, empty_accounts_store())
    return normalize_accounts_store(raw)


def save_accounts_store(store: dict[str, list[dict[str, Any]]]) -> None:
    write_json(ACCOUNTS_FILE, normalize_accounts_store(store))


def load_mnemonic_store() -> list[dict[str, Any]]:
    mnemonics: list[dict[str, Any]] = []
    for root in load_accounts_store()["roots"]:
        if root.get("kind") == "mnemonic":
            mnemonics.append(flatten_mnemonic_root(root))
    return mnemonics


def load_local_tokens() -> list[dict[str, Any]]:
    raw = read_json(TOKENS_FILE, [])
    if not isinstance(raw, list):
        raise WalletError(f"Invalid token cache format: {TOKENS_FILE}")
    return raw


def save_local_tokens(tokens: list[dict[str, Any]]) -> None:
    write_json(TOKENS_FILE, tokens)


def load_accounts() -> list[dict[str, Any]]:
    store = load_accounts_store()
    accounts: list[dict[str, Any]] = []
    for root in store["roots"]:
        if root.get("kind") == "private":
            root_name = str(root.get("name", "")).strip()
            if not root_name:
                continue
            accounts.append(
                {
                    "name": normalize_account_name(root_name),
                    "source_type": "private",
                    "root_name": root_name,
                    "address_type": normalize_address_family(root.get("address_type", "")),
                    "address": str(root.get("address", "")).strip(),
                    "private_key": str(root.get("private_key", {}).get("value", "")).strip(),
                    "masked": str(root.get("private_key", {}).get("masked", "")).strip(),
                    "created_at": root.get("created_at"),
                }
            )
            continue
        for family in SUPPORTED_ADDRESS_FAMILIES:
            for key in root["trees"][family]["keys"]:
                key_name = str(key.get("name", "")).strip()
                if not key_name:
                    continue
                entry = {
                    "name": normalize_account_name(key_name),
                    "source_type": root["kind"],
                    "root_name": root["name"],
                    "address_type": family,
                    "address": key.get("address", ""),
                    "private_key": key.get("private_key", {}).get("value", ""),
                    "masked": key.get("private_key", {}).get("masked", ""),
                    "created_at": key.get("created_at") or root.get("created_at"),
                }
                if root["kind"] == "mnemonic":
                    entry["mnemonic_name"] = root["name"]
                    entry["derivation_index"] = int(key.get("derivation_index", 0))
                accounts.append(entry)
    return accounts


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


def normalize_mnemonic_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise WalletError("Mnemonic name is required")
    return name


def find_mnemonic_root(name: str) -> dict[str, Any]:
    target = normalize_mnemonic_name(name)
    for root in load_accounts_store()["roots"]:
        if root.get("kind") == "mnemonic" and root.get("name") == target:
            return root
    raise WalletError(f"Unknown mnemonic: {target}")


def find_first_mnemonic_root() -> dict[str, Any] | None:
    mnemonics = sorted(
        (root for root in load_accounts_store()["roots"] if root.get("kind") == "mnemonic"),
        key=lambda item: item.get("name", ""),
    )
    return mnemonics[0] if mnemonics else None


def find_mnemonic(name: str) -> dict[str, Any]:
    return flatten_mnemonic_root(find_mnemonic_root(name))


def find_first_mnemonic() -> dict[str, Any] | None:
    root = find_first_mnemonic_root()
    return flatten_mnemonic_root(root) if root else None


def upsert_mnemonic(mnemonic_record: dict[str, Any]) -> None:
    store = load_accounts_store()
    created_at = mnemonic_record.get("created_at") or utc_now_iso()
    _, existing = find_root_in_store(store, "mnemonic", mnemonic_record["name"])
    root = (
        merge_mnemonic_root(existing, mnemonic_record["value"], created_at=created_at)
        if existing is not None
        else build_mnemonic_root_record(mnemonic_record["name"], mnemonic_record["value"], created_at=created_at)
    )
    root["created_at"] = created_at
    upserted = False
    for index, current in enumerate(store["roots"]):
        if current.get("kind") == "mnemonic" and current.get("name") == root["name"]:
            store["roots"][index] = root
            upserted = True
            break
    if not upserted:
        store["roots"].append(root)
    save_accounts_store(store)


def mnemonic_summary(mnemonic_record: dict[str, Any]) -> dict[str, Any]:
    return {
        "root_type": "mnemonic",
        "name": mnemonic_record["name"],
        "created_at": mnemonic_record.get("created_at"),
        "masked": mnemonic_record.get("masked"),
        "branches": mnemonic_record.get("branches", {}),
    }


def remember_mnemonic(name: str, value: str) -> dict[str, Any]:
    name = normalize_mnemonic_name(name)
    normalized = validate_mnemonic(value)
    created_at = utc_now_iso()
    record = {
        "name": name,
        "value": normalized,
        "masked": mask_mnemonic(normalized),
        "created_at": created_at,
    }
    upsert_mnemonic(record)
    return find_mnemonic(name)


def build_private_account_record(name: str, chain: str, value: str) -> dict[str, Any]:
    chain = normalize_chain(chain)
    created_at = utc_now_iso()
    _, key_node = build_private_key_node(chain, value, created_at=created_at)
    return {
        "name": normalize_account_name(name),
        "chain": chain,
        "source_type": "private",
        "root_name": normalize_account_name(name),
        "address_type": address_family_for_chain(chain),
        "address": key_node["address"],
        "private_key": key_node["private_key"]["value"],
        "masked": key_node["private_key"]["masked"],
        "created_at": created_at,
    }


def account_address_family(account_record: dict[str, Any]) -> str:
    family = str(account_record.get("address_type", "")).strip()
    if family:
        return normalize_address_family(family)
    chain = str(account_record.get("chain", "")).strip()
    if chain:
        return address_family_for_chain(chain)
    raise WalletError(f"Account {account_record.get('name', '<unknown>')} is missing address_type")


def account_supports_chain(account_record: dict[str, Any], chain: str) -> bool:
    return account_address_family(account_record) == address_family_for_chain(chain)


def default_chain_for_account(account_record: dict[str, Any]) -> str:
    family = account_address_family(account_record)
    return FAMILY_CHAINS[family][0]


def account_summary(account_record: dict[str, Any]) -> dict[str, Any]:
    address_type = account_address_family(account_record)
    summary = {
        "name": account_record["name"],
        "source_type": account_record["source_type"],
        "root_name": account_record.get("root_name") or account_record.get("mnemonic_name") or account_record["name"],
        "address_type": address_type,
        "tree_path": account_tree_path(account_record),
        "address": account_record.get("address"),
        "created_at": account_record.get("created_at"),
    }
    if account_record.get("source_type") == "private":
        summary["masked"] = account_record.get("masked") or mask_secret(account_record.get("private_key", ""))
    if account_record.get("source_type") == "mnemonic":
        summary["mnemonic_name"] = account_record.get("mnemonic_name")
        summary["derivation_index"] = int(account_record.get("derivation_index", 0))
    return summary


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


def derive_tron_private_key_from_mnemonic(mnemonic: str, index: int = 0) -> str:
    index = normalize_derivation_index(index)
    seed = Bip39SeedGenerator(mnemonic).Generate()
    ctx = (
        Bip44.FromSeed(seed, Bip44Coins.TRON)
        .Purpose()
        .Coin()
        .Account(0)
        .Change(Bip44Changes.CHAIN_EXT)
        .AddressIndex(index)
    )
    return "0x" + ctx.PrivateKey().Raw().ToHex()


def evm_account_from_private_key(private_key: str) -> Any:
    return Account.from_key(private_key)


def tron_address_from_private_key(private_key: str) -> str:
    account = evm_account_from_private_key(private_key)
    uncompressed_public_key = b"\x04" + account._key_obj.public_key.to_bytes()
    return TrxAddrEncoder.EncodeKey(uncompressed_public_key)


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
    if chain and not account_supports_chain(account, chain):
        if not explicit_name:
            return None
        raise WalletError(
            f"Account {selected_name} is {account_address_family(account)}, not compatible with requested chain {normalize_chain(chain)}"
        )
    return account


def find_first_matching_account(chain: str | None = None, source_type: str | None = None) -> dict[str, Any] | None:
    for account in sorted(load_accounts(), key=lambda item: item.get("name", "")):
        if source_type and account.get("source_type") != source_type:
            continue
        if chain and not account_supports_chain(account, chain):
            continue
        return account
    return None


def find_existing_mnemonic_account(mnemonic_name: str, family: str, derivation_index: int) -> dict[str, Any] | None:
    target_mnemonic = normalize_mnemonic_name(mnemonic_name)
    target_family = normalize_address_family(family)
    target_index = normalize_derivation_index(derivation_index)
    for account in load_accounts():
        if account.get("source_type") != "mnemonic":
            continue
        if account.get("mnemonic_name") != target_mnemonic:
            continue
        if account_address_family(account) != target_family:
            continue
        if int(account.get("derivation_index", 0)) != target_index:
            continue
        return account
    return None


def derive_address_from_mnemonic_value(chain: str, mnemonic: str, index: int = 0) -> str:
    chain = normalize_chain(chain)
    if chain in EVM_CHAINS:
        private_key = derive_evm_private_key_from_mnemonic(mnemonic, index=index)
        return evm_account_from_private_key(private_key).address
    if chain in TVM_CHAINS:
        private_key = derive_tron_private_key_from_mnemonic(mnemonic, index=index)
        return tron_address_from_private_key(private_key)
    return str(derive_solana_keypair_from_mnemonic(mnemonic, index=index).pubkey())


def derive_account_address(account: dict[str, Any], chain: str | None = None) -> str:
    requested_chain = normalize_chain(chain) if chain else default_chain_for_account(account)
    if not account_supports_chain(account, requested_chain):
        raise WalletError(f"Account {account['name']} is not compatible with {requested_chain}")

    address = str(account.get("address", "")).strip()
    if address:
        return address

    source_type = account["source_type"]
    if source_type == "mnemonic":
        mnemonic_name = account.get("mnemonic_name", "").strip()
        if not mnemonic_name:
            raise WalletError(f"Account {account['name']} is missing mnemonic_name")
        mnemonic = find_mnemonic(mnemonic_name)
        return derive_address_from_mnemonic_value(requested_chain, mnemonic["value"], index=int(account.get("derivation_index", 0)))
    if source_type == "private":
        private_key = account.get("private_key", "").strip()
        if not private_key:
            raise WalletError(f"Account {account['name']} is missing private_key")
        if requested_chain in EVM_CHAINS:
            return evm_account_from_private_key(private_key).address
        if requested_chain in TVM_CHAINS:
            return tron_address_from_private_key(private_key)
        return str(solana_keypair_from_private_value(private_key).pubkey())
    raise WalletError(f"Unsupported account source: {source_type}")


def resolve_fallback_address(chain: str, source: str) -> tuple[str, str]:
    chain = normalize_chain(chain)
    if source == "private":
        account = find_first_matching_account(chain, "private")
        if not account:
            raise WalletError(f"No stored private account for {chain}")
        return f"account:{account['name']}", derive_account_address(account, chain)

    if source == "mnemonic":
        account = find_first_matching_account(chain, "mnemonic")
        if account:
            return f"account:{account['name']}", derive_account_address(account, chain)
        mnemonic = find_first_mnemonic()
        if not mnemonic:
            raise WalletError(f"No stored mnemonic available for {chain}")
        return f"mnemonic:{mnemonic['name']}", derive_address_from_mnemonic_value(chain, mnemonic["value"], index=0)

    if source == "auto":
        for source_type in ("private", "mnemonic"):
            account = find_first_matching_account(chain, source_type)
            if account:
                return f"account:{account['name']}", derive_account_address(account, chain)
        mnemonic = find_first_mnemonic()
        if mnemonic:
            return f"mnemonic:{mnemonic['name']}", derive_address_from_mnemonic_value(chain, mnemonic["value"], index=0)
        raise WalletError(f"No local account available for {chain}")

    raise WalletError(f"Unsupported source: {source}")


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

    source_label, address = resolve_fallback_address(chain, source)
    return source_label, address, None


def upsert_account(account_record: dict[str, Any]) -> None:
    store = load_accounts_store()
    remove_account_name_from_store(store, account_record["name"])

    if account_record["source_type"] == "private":
        root = build_private_root_record(
            account_record["name"],
            account_record["chain"],
            account_record["private_key"],
            created_at=account_record.get("created_at"),
        )
        for index, existing in enumerate(store["roots"]):
            if existing.get("kind") == "private" and existing.get("name") == root["name"]:
                store["roots"][index] = root
                break
        else:
            store["roots"].append(root)
        save_accounts_store(store)
        return

    if account_record["source_type"] != "mnemonic":
        raise WalletError(f"Unsupported account source: {account_record['source_type']}")

    mnemonic_name = normalize_mnemonic_name(str(account_record.get("mnemonic_name", "")))
    derivation_index = int(account_record.get("derivation_index", 0))
    chain = normalize_chain(account_record["chain"])
    family = address_family_for_chain(chain)
    index, root = find_root_in_store(store, "mnemonic", mnemonic_name)
    if root is None:
        raise WalletError(f"Unknown mnemonic: {mnemonic_name}")
    key_node = find_or_create_key_node(root, family, derivation_index, created_at=account_record.get("created_at"))
    assign_key_name(key_node, account_record["name"], account_record.get("created_at"))
    if not key_node.get("address") and account_record.get("address"):
        key_node["address"] = account_record["address"]
    if index is not None:
        store["roots"][index] = root
    save_accounts_store(store)


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


def tron_post(url: str, path: str, payload: dict[str, Any]) -> Any:
    endpoint = url.rstrip("/") + "/" + path.lstrip("/")
    body = json.dumps(payload).encode("utf-8")
    request = Request(endpoint, data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise WalletError(f"TRON HTTP error: {exc.code} {detail}") from exc
    except URLError as exc:
        raise WalletError(f"TRON connection error: {exc.reason}") from exc
    data = json.loads(response_body)
    if isinstance(data, dict) and data.get("Error"):
        raise WalletError(f"TRON RPC error: {data['Error']}")
    return data


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


def query_tron_balances(address: str) -> dict[str, Any]:
    rpc_url = require_rpc_url("tron")
    account = tron_post(rpc_url, "/wallet/getaccount", {"address": address, "visible": True})

    assets: list[dict[str, Any]] = []
    native_raw = int(account.get("balance", 0) or 0)
    if native_raw > 0:
        native_meta = NATIVE_ASSETS["tron"]
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

    return {"chain": "tron", "address": address, "assets": assets}


def resolve_evm_private_key(
    source: str = "auto",
    index: int = 0,
    mnemonic_name: str | None = None,
) -> tuple[str, str, str]:
    if source == "private":
        account = find_first_matching_account("ethereum", "private")
        if not account:
            raise WalletError("No stored private account for ethereum")
        private_key = account.get("private_key", "").strip()
        if not private_key:
            raise WalletError(f"Account {account['name']} is missing private_key")
        return f"account:{account['name']}", private_key, derive_account_address(account, "ethereum")

    if source == "mnemonic":
        if mnemonic_name is None:
            mnemonic_account = find_first_matching_account("ethereum", "mnemonic")
            if mnemonic_account:
                stored_private_key = mnemonic_account.get("private_key", "").strip()
                if not stored_private_key:
                    raise WalletError(f"Account {mnemonic_account['name']} is missing private_key")
                return (
                    f"account:{mnemonic_account['name']}",
                    stored_private_key,
                    derive_account_address(mnemonic_account, "ethereum"),
                )
        if mnemonic_name:
            mnemonic_account = find_existing_mnemonic_account(mnemonic_name, "evm", index)
            if mnemonic_account:
                stored_private_key = mnemonic_account.get("private_key", "").strip()
                if not stored_private_key:
                    raise WalletError(f"Account {mnemonic_account['name']} is missing private_key")
                return (
                    f"account:{mnemonic_account['name']}",
                    stored_private_key,
                    derive_account_address(mnemonic_account, "ethereum"),
                )
        mnemonic = find_mnemonic(mnemonic_name) if mnemonic_name else find_first_mnemonic()
        if not mnemonic:
            raise WalletError("No stored mnemonic available for ethereum")
        private_key = derive_evm_private_key_from_mnemonic(mnemonic["value"], index=index)
        return f"mnemonic:{mnemonic['name']}", private_key, evm_account_from_private_key(private_key).address

    if source == "auto":
        account = find_first_matching_account("ethereum", "private")
        if account:
            private_key = account.get("private_key", "").strip()
            if not private_key:
                raise WalletError(f"Account {account['name']} is missing private_key")
            return f"account:{account['name']}", private_key, derive_account_address(account, "ethereum")
        mnemonic_account = find_first_matching_account("ethereum", "mnemonic")
        if mnemonic_account:
            return resolve_evm_private_key(
                "mnemonic",
                index=int(mnemonic_account.get("derivation_index", 0)),
                mnemonic_name=mnemonic_account.get("mnemonic_name"),
            )
        mnemonic = find_first_mnemonic()
        if mnemonic:
            return resolve_evm_private_key("mnemonic", index=index, mnemonic_name=mnemonic["name"])
        raise WalletError("No local account available for ethereum")

    raise WalletError(f"Unsupported source: {source}")


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
                mnemonic_name=account.get("mnemonic_name"),
            )
        elif account["source_type"] == "private":
            private_key = account.get("private_key", "").strip()
            if not private_key:
                raise WalletError(f"Account {account['name']} is missing private_key")
            address = derive_account_address(account, chain)
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
    chain = require_evm_chain(chain, "ERC-20 operations")
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
    chain = require_evm_chain(chain, "ERC-20 operations")
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
    chain = require_evm_chain(chain, "ERC-20 operations")
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
    mnemonic_record = remember_mnemonic(args.name, mnemonic)
    evm_address = derive_address_from_mnemonic_value("ethereum", mnemonic_record["value"], index=0)
    solana_address = derive_address_from_mnemonic_value("solana", mnemonic_record["value"], index=0)
    tron_address = derive_address_from_mnemonic_value("tron", mnemonic_record["value"], index=0)
    print_json(
        {
            "status": "ok",
            "stored": [str(ACCOUNTS_FILE)],
            "mnemonic": mnemonic_summary(mnemonic_record),
            "addresses": {
                "ethereum": evm_address,
                "bsc": evm_address,
                "base": evm_address,
                "solana": solana_address,
                "tron": tron_address,
            },
        }
    )


def cmd_mnemonic_import(args: argparse.Namespace) -> None:
    mnemonic = validate_mnemonic(read_secret_value(args.value, args.stdin, "mnemonic"))
    mnemonic_record = remember_mnemonic(args.name, mnemonic)
    evm_address = derive_address_from_mnemonic_value("ethereum", mnemonic_record["value"], index=0)
    solana_address = derive_address_from_mnemonic_value("solana", mnemonic_record["value"], index=0)
    tron_address = derive_address_from_mnemonic_value("tron", mnemonic_record["value"], index=0)
    print_json(
        {
            "status": "ok",
            "stored": [str(ACCOUNTS_FILE)],
            "mnemonic": mnemonic_summary(mnemonic_record),
            "addresses": {
                "ethereum": evm_address,
                "bsc": evm_address,
                "base": evm_address,
                "solana": solana_address,
                "tron": tron_address,
            },
        }
    )


def cmd_mnemonic_list(_: argparse.Namespace) -> None:
    mnemonics = [mnemonic_summary(item) for item in sorted(load_mnemonic_store(), key=lambda entry: entry.get("name", ""))]
    print_json({"status": "ok", "stored": str(ACCOUNTS_FILE), "mnemonics": mnemonics})


def cmd_mnemonic_show(args: argparse.Namespace) -> None:
    mnemonic_record = find_mnemonic(args.name)
    print_json({"status": "ok", "stored": str(ACCOUNTS_FILE), "mnemonic": mnemonic_summary(mnemonic_record)})


def cmd_private_generate(args: argparse.Namespace) -> None:
    chain = normalize_chain(args.chain)
    if chain in EVM_CHAINS or chain in TVM_CHAINS:
        private_key = "0x" + secrets.token_hex(32)
    else:
        private_key = str(Keypair())
    record = build_private_account_record(args.name, chain, private_key)
    upsert_account(record)
    print_json(
        {
            "status": "ok",
            "chain": chain,
            "stored": [str(ACCOUNTS_FILE)],
            "account": account_summary(record),
        }
    )


def cmd_private_import(args: argparse.Namespace) -> None:
    chain = normalize_chain(args.chain)
    raw_value = read_secret_value(args.value, args.stdin, "private key")
    record = build_private_account_record(args.name, chain, raw_value)
    upsert_account(record)
    print_json(
        {
            "status": "ok",
            "chain": chain,
            "stored": [str(ACCOUNTS_FILE)],
            "account": account_summary(record),
        }
    )


def cmd_account_add(args: argparse.Namespace) -> None:
    chain = normalize_chain(args.chain)
    name = normalize_account_name(args.name)
    derivation_index = normalize_derivation_index(args.index)
    mnemonic_name = normalize_mnemonic_name(args.source_name)
    family = address_family_for_chain(chain)
    previous_account = find_existing_mnemonic_account(mnemonic_name, family, derivation_index)
    previous_name = previous_account["name"] if previous_account else None
    active_name = load_active_account_name()
    mnemonic = find_mnemonic(mnemonic_name)
    address = derive_address_from_mnemonic_value(chain, mnemonic["value"], index=derivation_index)

    record = {
        "name": name,
        "chain": chain,
        "source_type": "mnemonic",
        "mnemonic_name": mnemonic_name,
        "derivation_index": derivation_index,
        "address": address,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    upsert_account(record)

    activated = False
    if args.use or active_name is None or (previous_name and active_name == previous_name):
        save_active_account_name(name)
        activated = True

    print_json(
        {
            "status": "ok",
            "account": account_summary(record),
            "stored": str(ACCOUNTS_FILE),
            "active": activated,
            "active_file": str(ACTIVE_ACCOUNT_FILE),
        }
    )


def cmd_account_list(_: argparse.Namespace) -> None:
    active_name = load_active_account_name()
    accounts: list[dict[str, Any]] = []
    for account in sorted(load_accounts(), key=lambda item: item.get("name", "")):
        entry = account_summary(account)
        entry["active"] = account.get("name") == active_name
        accounts.append(entry)
    print_json({"status": "ok", "active_account": active_name, "accounts": accounts})


def cmd_account_show(args: argparse.Namespace) -> None:
    account = get_selected_account(args.name)
    if not account:
        raise WalletError("No active account selected")
    print_json({"status": "ok", "active_account": load_active_account_name(), "account": account_summary(account)})


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

    source, address = resolve_fallback_address(chain, args.source)
    print_json({"status": "ok", "chain": chain, "source": source, "address": address})


def cmd_balances(args: argparse.Namespace) -> None:
    chain = normalize_chain(args.chain)
    source, address, account_name = resolve_query_target(chain, args.account, args.address, args.source)

    if chain == "solana":
        result = query_solana_balances(address)
    elif chain == "tron":
        result = query_tron_balances(address)
    else:
        result = query_evm_balances(chain, address)
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

    mnemonic_parser = subparsers.add_parser("mnemonic", help="Generate, import, or inspect named mnemonics in .accounts")
    mnemonic_subparsers = mnemonic_parser.add_subparsers(dest="mnemonic_command", required=True)

    mnemonic_generate = mnemonic_subparsers.add_parser("generate", help="Generate and store a named mnemonic")
    mnemonic_generate.add_argument("--name", required=True, help="Mnemonic name")
    mnemonic_generate.set_defaults(func=cmd_mnemonic_generate)

    mnemonic_import = mnemonic_subparsers.add_parser("import", help="Import and store a named mnemonic")
    mnemonic_import.add_argument("--name", required=True, help="Mnemonic name")
    mnemonic_import.add_argument("--value", help="Mnemonic value")
    mnemonic_import.add_argument("--stdin", action="store_true", help="Read mnemonic from stdin")
    mnemonic_import.set_defaults(func=cmd_mnemonic_import)

    mnemonic_list = mnemonic_subparsers.add_parser("list", help="List stored mnemonic roots")
    mnemonic_list.set_defaults(func=cmd_mnemonic_list)

    mnemonic_show = mnemonic_subparsers.add_parser("show", help="Show one mnemonic summary")
    mnemonic_show.add_argument("--name", required=True)
    mnemonic_show.set_defaults(func=cmd_mnemonic_show)

    private_parser = subparsers.add_parser("private", help="Generate or import a private-key account")
    private_subparsers = private_parser.add_subparsers(dest="private_command", required=True)

    private_generate = private_subparsers.add_parser("generate", help="Generate and store a private-key account")
    private_generate.add_argument("--chain", required=True)
    private_generate.add_argument("--name", required=True, help="Account name")
    private_generate.set_defaults(func=cmd_private_generate)

    private_import = private_subparsers.add_parser("import", help="Import and store a private-key account")
    private_import.add_argument("--chain", required=True)
    private_import.add_argument("--name", required=True, help="Account name")
    private_import.add_argument("--value", help="Private key value")
    private_import.add_argument("--stdin", action="store_true", help="Read private key from stdin")
    private_import.set_defaults(func=cmd_private_import)

    account_parser = subparsers.add_parser("account", help="Create and manage named wallet accounts")
    account_subparsers = account_parser.add_subparsers(dest="account_command", required=True)

    account_add = account_subparsers.add_parser("add", help="Add or update a mnemonic-derived account")
    account_add.add_argument("--name", required=True)
    account_add.add_argument("--chain", required=True)
    account_add.add_argument("--source", choices=["mnemonic"], required=True)
    account_add.add_argument("--source-name", required=True, help="Mnemonic root name")
    account_add.add_argument("--index", type=int, default=0, help="Mnemonic derivation index")
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
