# UXUY DEX Gateway Usage Reference

Use this file when the user asks for concrete `curl` examples, fixed `appId` details, or a no-auth request template.

## Gateway Contract

- Base host: `https://gwapi.ourdex.com`
- Path shape: `/{chain}/07541bf85df2072a9e0d0b2a964dc718`
- Required header: `Content-Type: application/json`
- Supported chains: `bnbchain`, `solana`, `base`, `xlayer`, `ethereum`

## Access Rules

- Always use `07541bf85df2072a9e0d0b2a964dc718` as the path `appId`.
- Do not add an `Authorization` header for this app.
- Use HTTPS only.
- Treat `bnbchain` as the canonical chain name for BSC.

## curl Examples

Chain status:

```bash
curl https://gwapi.ourdex.com/bnbchain/07541bf85df2072a9e0d0b2a964dc718 \
  -H 'Content-Type: application/json' \
  --data '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"dex_status",
    "params":[]
  }'
```

One token:

```bash
curl https://gwapi.ourdex.com/bnbchain/07541bf85df2072a9e0d0b2a964dc718 \
  -H 'Content-Type: application/json' \
  --data '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"dex_getCoin",
    "params":["0x1234567890abcdef1234567890abcdef12345678"]
  }'
```

24h quote summary:

```bash
curl https://gwapi.ourdex.com/bnbchain/07541bf85df2072a9e0d0b2a964dc718 \
  -H 'Content-Type: application/json' \
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
curl https://gwapi.ourdex.com/bnbchain/07541bf85df2072a9e0d0b2a964dc718 \
  -H 'Content-Type: application/json' \
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
- JSON-RPC body is valid JSON
- `method` and `params` match the requested RPC
