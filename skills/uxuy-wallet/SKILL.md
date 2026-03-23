---
name: uxuy-wallet
description: Use this skill when the user wants to create or manage a local Web3 wallet, generate or import a mnemonic or private key, derive addresses for bsc, base, ethereum, tron, or solana, query balances for tracked assets, or query, approve, or transfer an ERC-20 token on bsc, base, or ethereum from a local wallet.
---

# UXUY Wallet

Use this skill to manage a local wallet through one Python CLI:

```bash
python scripts/wallet.py <command> ...
```

The script stores local state under `~/.uxuy-wallet/` by default:

- `.tokens`: locally discovered ERC-20 tokens that were queried before
- `.accounts`: one tree store whose top-level `roots` are named `mnemonic` or `private` secrets
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

- Address derivation: `bsc`, `base`, `ethereum`, `tron`, `solana`
- Balance query: `bsc`, `base`, `ethereum`, `tron`, `solana`
- ERC-20 query / approve / transfer: `bsc`, `base`, `ethereum`

Required RPC env vars:

- `BSC_RPC_URL`
- `BASE_RPC_URL`
- `ETHEREUM_RPC_URL`
- `TRON_RPC_URL`
- `SOLANA_RPC_URL`

## Command Map

Mnemonic management:

```bash
python scripts/wallet.py mnemonic generate --name seed-main
python scripts/wallet.py mnemonic import --name seed-backup --stdin
python scripts/wallet.py mnemonic import --name seed-main --value "word1 word2 ..."
python scripts/wallet.py mnemonic list
python scripts/wallet.py mnemonic show --name seed-main
```

Private key management:

```bash
python scripts/wallet.py private generate --chain ethereum --name trading-eth
python scripts/wallet.py private generate --chain bsc --name trading-bsc
python scripts/wallet.py private generate --chain tron --name trading-trx
python scripts/wallet.py private generate --chain solana --name sol-main
python scripts/wallet.py private import --chain base --name base-hot --stdin
python scripts/wallet.py private import --chain bsc --name trading-bsc --stdin
python scripts/wallet.py private import --chain tron --name trading-trx --stdin
python scripts/wallet.py private import --chain solana --name sol-main --value "<private>"
```

Address derivation:

```bash
python scripts/wallet.py address show --chain bsc
python scripts/wallet.py address show --chain tron
python scripts/wallet.py address show --chain solana --source mnemonic
python scripts/wallet.py address show --chain bsc --account trading
```

Balance query:

```bash
python scripts/wallet.py balances --chain ethereum
python scripts/wallet.py balances --chain tron --account main-tron
python scripts/wallet.py balances --chain solana --address <address>
python scripts/wallet.py balances --chain bsc --account main-bsc
```

Account management:

```bash
python scripts/wallet.py account add --name main-bsc --chain bsc --source mnemonic --source-name seed-main --index 0 --use
python scripts/wallet.py account add --name main-tron --chain tron --source mnemonic --source-name seed-main --index 0
python scripts/wallet.py account add --name main-sol --chain solana --source mnemonic --source-name seed-main --index 0
python scripts/wallet.py account list
python scripts/wallet.py account show
python scripts/wallet.py account use --name trading-bsc
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

- `.accounts` is the single wallet state file and stores a `roots` tree. Each root is either a named `mnemonic` or a named `private` secret.
- Mnemonic roots branch into `evm`, `svm`, and `tvm`, and all three families now store derived keys and addresses.
- Each branch stores private-key material, the derived address, and an optional key-level account name.
- Private-key imports are stored as a single-leaf private root: one `address_type`, one private key, and one address. They do not create empty `evm` / `svm` / `tvm` branches.
- `tron` maps to the `tvm` branch and uses the standard TRON BIP44 derivation path for mnemonic-derived keys.
- The `mnemonic` commands operate on mnemonic roots inside `.accounts`.
- Private-key account records keep the address and private key together in the tree, but command output only shows masked private-key status.
- Mnemonic-derived accounts store the account name, derivation index, and the `mnemonic_name` they come from. Account-facing output summarizes the branch `address_type` instead of any chain label.
- This storage model is a direct switch. Older `.accounts` layouts do not need to be preserved.
- EVM private-key accounts can be reused across `bsc`, `base`, and `ethereum`.
- Mnemonic accounts support multiple derivation indexes and can be saved as separate named accounts.
- Solana uses the standard Solana BIP44 path when deriving from the mnemonic.
- TRON uses the standard TRON BIP44 path when deriving from the mnemonic.
- `balances --chain tron` supports native `TRX` balance queries. TRC-20 query / approve / transfer are not supported yet.
- Balance queries only return native assets or tracked tokens with balance greater than zero.
- Tracked tokens come from `scripts/main_tokens.json` plus locally discovered tokens in `~/.uxuy-wallet/.tokens`.
- `balances`, `token query`, `token approve`, and `token transfer` should prefer `--account`; if it is omitted, use the active account from `~/.uxuy-wallet/.active` when present.
- `token query` always returns ERC-20 metadata and `total_supply`, and can also return holder balance or allowance.
- `token query`, `token approve`, and `token transfer` accept either a token address or a known token symbol/name already present in `main_tokens.json` or `.tokens`.
- If a user queries an ERC-20 token by address and it is not in `main_tokens.json`, cache it in `.tokens` for later reuse.
- `token approve` and `token transfer` only work on EVM chains and sign with the selected account, or with the local fallback account state if no account is selected.
- If the user asks to create or deploy a token, explain that this version does not include token deployment.

## Working Style

When using this skill:

1. Pick the exact chain and command first.
2. Prefer `--stdin` for imports when handling mnemonics or private keys.
3. Prefer named accounts for everyday operations instead of relying on fallback resolution.
4. If no `--account` is supplied, the script will use the active account when one exists.
5. If no address is supplied for `balances`, let the script derive the target from the selected account or local wallet state.
6. When reporting results, show the account name, derived address, and masked secret status, not the raw mnemonic or private key.
7. When a balance command returns no assets, state that the tracked assets on that chain are all zero.
