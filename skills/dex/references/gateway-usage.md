# UXUY DEX Gateway Usage Reference

Use this file when the user asks for concrete `curl` examples, fixed `appId` details, or a no-auth request template.

## Gateway Contract

- Base host: `https://gwapi.ourdex.com`
- Path shape: `/{chain}/07541bf85df2072a9e0d0b2a964dc718`
- Required header: `Content-Type: application/json`
- Required header: `x-uxuy-dex-skill: <local hash>`
- Supported chains: `bnbchain`, `solana`, `base`, `xlayer`, `ethereum`

## Access Rules

- Always use `07541bf85df2072a9e0d0b2a964dc718` as the path `appId`.
- Do not add an `Authorization` header for this app.
- Use HTTPS only.
- Treat `bnbchain` as the canonical chain name for BSC.

## Local Hash Header

Before each real gateway request, load the local skill hash:

```bash
HASH="$(./scripts/get-hash.sh)"
```

Behavior:

- On first use, the script creates `.hash`
- The file stores one 64-character lowercase hex value
- Later requests reuse the same value
- If `.hash` is empty or malformed, the script regenerates it

Send that value in every request:

```http
x-uxuy-dex-skill: <hash>
```

## curl Examples

Chain status:

```bash
HASH="$(./scripts/get-hash.sh)"

curl https://gwapi.ourdex.com/bnbchain/07541bf85df2072a9e0d0b2a964dc718 \
  -H 'Content-Type: application/json' \
  -H "x-uxuy-dex-skill: ${HASH}" \
  --data '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"dex_status",
    "params":[]
  }'
```

One token:

```bash
HASH="$(./scripts/get-hash.sh)"

curl https://gwapi.ourdex.com/bnbchain/07541bf85df2072a9e0d0b2a964dc718 \
  -H 'Content-Type: application/json' \
  -H "x-uxuy-dex-skill: ${HASH}" \
  --data '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"dex_getCoin",
    "params":["0x1234567890abcdef1234567890abcdef12345678"]
  }'
```

24h quote summary:

```bash
HASH="$(./scripts/get-hash.sh)"

curl https://gwapi.ourdex.com/bnbchain/07541bf85df2072a9e0d0b2a964dc718 \
  -H 'Content-Type: application/json' \
  -H "x-uxuy-dex-skill: ${HASH}" \
  --data '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"dex_getQuote",
    "params":[
      "0x1234567890abcdef1234567890abcdef12345678",
      {"target":"token","start":"-24h"}
    ]
  }'
```

24h hot ranking:

```bash
HASH="$(./scripts/get-hash.sh)"

curl https://gwapi.ourdex.com/bnbchain/07541bf85df2072a9e0d0b2a964dc718 \
  -H 'Content-Type: application/json' \
  -H "x-uxuy-dex-skill: ${HASH}" \
  --data '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"dex_ranking",
    "params":[
      {"target":"token/hot","start":"-24h","size":10}
    ]
  }'
```

## Troubleshooting

If a request fails, check these first:

- `chain` is one of the supported chain names
- URL path is exactly `/{chain}/07541bf85df2072a9e0d0b2a964dc718`
- `Content-Type` is `application/json`
- `x-uxuy-dex-skill` is present and loaded from `./scripts/get-hash.sh`
- JSON-RPC body is valid JSON
- `method` and `params` match the requested RPC
