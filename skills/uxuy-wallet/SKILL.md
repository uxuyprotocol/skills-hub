---
name: uxuy-wallet
description: Use this skill when the user wants to create or manage a local Web3 wallet, generate or import a mnemonic or private key, derive addresses for bsc, base, ethereum, or solana, query balances for tracked assets, or query, approve, or transfer an ERC-20 token on bsc, base, or ethereum from a local wallet.
---

# UXUY Wallet

Use this skill to manage a local wallet through one Python CLI:

```bash
python scripts/wallet.py <command> ...
```

The script stores local state under `~/.uxuy-wallet/` by default:

- `.mnemonic`: active mnemonic
- `.private`: imported or generated private keys
- `.secrets`: named mnemonic/private secrets for multi-account use
- `.tokens`: locally discovered ERC-20 tokens that were queried before
- `.accounts`: named accounts that map to mnemonic/private sources
- `.active`: current default account name

Set `UXUY_WALLET_HOME` to override the storage directory.

## Environment

Run commands from the current skill directory:

```bash
python scripts/wallet.py --help
```

Install Python dependencies before using the script:

```bash
pip install bip_utils web3 solana solders
```

Use the Python interpreter where those dependencies are installed. In this repo, prefer `python` if `python3` cannot import the wallet dependencies.

## Security

Follow these rules when using this skill:

- Never print the full mnemonic or full private key in normal output.
- Prefer `--stdin` for imports so secrets do not end up in shell history.
- Do not ask the user to paste secrets unless the task requires import.
- Do not move secrets into logs, examples, or markdown tables.

## Chains

Supported chains:

- Address derivation: `bsc`, `base`, `ethereum`, `solana`
- Balance query: `bsc`, `base`, `ethereum`, `solana`
- ERC-20 query / approve / transfer: `bsc`, `base`, `ethereum`

Required RPC env vars:

- `BSC_RPC_URL`
- `BASE_RPC_URL`
- `ETHEREUM_RPC_URL`
- `SOLANA_RPC_URL`

## Command Map

Mnemonic management:

```bash
python scripts/wallet.py mnemonic generate
python scripts/wallet.py mnemonic generate --name seed-main
python scripts/wallet.py mnemonic import --stdin
python scripts/wallet.py mnemonic import --name seed-backup --stdin
python scripts/wallet.py mnemonic import --value "word1 word2 ..."
```

Private key management:

```bash
python scripts/wallet.py private generate --chain ethereum
python scripts/wallet.py private generate --chain bsc --name trading-key
python scripts/wallet.py private generate --chain solana
python scripts/wallet.py private import --chain base --stdin
python scripts/wallet.py private import --chain bsc --name trading-key --stdin
python scripts/wallet.py private import --chain solana --value "<private>"
```

Secret management:

```bash
python scripts/wallet.py secret list
python scripts/wallet.py secret show --name seed-main
python scripts/wallet.py secret show --name default-evm-private
```

Address derivation:

```bash
python scripts/wallet.py address show --chain bsc
python scripts/wallet.py address show --chain solana --source mnemonic
python scripts/wallet.py address show --chain bsc --account trading
```

Balance query:

```bash
python scripts/wallet.py balances --chain ethereum
python scripts/wallet.py balances --chain solana --address <address>
python scripts/wallet.py balances --chain bsc --account main-bsc
```

Account management:

```bash
python scripts/wallet.py account add --name main-bsc --chain bsc --source mnemonic --source-name seed-main --index 0 --use
python scripts/wallet.py account add --name main-sol --chain solana --source mnemonic --source-name seed-main --index 0
python scripts/wallet.py account add --name trading --chain bsc --source private --source-name trading-key
python scripts/wallet.py account list
python scripts/wallet.py account show
python scripts/wallet.py account use --name trading
```

ERC-20 operations:

```bash
python scripts/wallet.py token query --chain ethereum --token 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48
python scripts/wallet.py token query --chain base --token USDC --account main-bsc
python scripts/wallet.py token query --chain base --token 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 --owner 0xOwner --spender 0xSpender
python scripts/wallet.py token approve --chain ethereum --token USDC --account main-bsc --spender 0xSpender --amount 100
python scripts/wallet.py token transfer --chain base --token 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 --account trading --to 0xReceiver --amount 1.5
```

## Behavior Notes

- EVM chains derive from the same mnemonic path and the same stored EVM private key slot.
- Named accounts sit above secrets and let the user choose an address explicitly instead of relying on whichever mnemonic/private key is currently available.
- Named secrets sit below accounts and let the user keep multiple mnemonics or private keys locally without overwriting the legacy `.mnemonic` / `.private` slots.
- Mnemonic accounts support multiple derivation indexes and can be saved as separate named accounts.
- Solana uses the standard Solana BIP44 path when deriving from the mnemonic.
- Balance queries only return native assets or tracked tokens with balance greater than zero.
- Tracked tokens come from `scripts/main_tokens.json` plus locally discovered tokens in `~/.uxuy-wallet/.tokens`.
- `balances`, `token query`, `token approve`, and `token transfer` should prefer `--account`; if it is omitted, use the active account from `~/.uxuy-wallet/.active` when present.
- `token query` always returns ERC-20 metadata and `total_supply`, and can also return holder balance or allowance.
- `token query`, `token approve`, and `token transfer` accept either a token address or a known token symbol/name already present in `main_tokens.json` or `.tokens`.
- If a user queries an ERC-20 token by address and it is not in `main_tokens.json`, cache it in `.tokens` for later reuse.
- `token approve` and `token transfer` only work on EVM chains and sign with the selected account, or with the raw mnemonic/private fallback if no account is selected.
- If the user needs to manage multiple private keys or mnemonics, create named secrets first, then bind named accounts to those secrets.
- If the user asks to create or deploy a token, explain that this version does not include token deployment.

## Working Style

When using this skill:

1. Pick the exact chain and command first.
2. Prefer `--stdin` for imports when handling secrets.
3. Prefer named accounts for everyday operations instead of relying on the default secret directly.
4. If no `--account` is supplied, the script will use the active account when one exists.
5. If no address is supplied for `balances`, let the script derive the target from the selected account or local wallet state.
6. When reporting results, show the account name, derived address, and masked secret status, not the raw mnemonic or private key.
7. When a balance command returns no assets, state that the tracked assets on that chain are all zero.
