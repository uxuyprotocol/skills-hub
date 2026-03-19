---
name: uxuy-dex
description: Use this skill when the user wants to query UXUY DEX market data through the public RPC gateway on bnbchain, solana, base, xlayer, or ethereum. This skill is configured to use appId 07541bf85df2072a9e0d0b2a964dc718 and does not require JWT authentication.
---

# UXUY DEX

Use this skill to map a market-data question to the correct UXUY DEX JSON-RPC method and produce a ready-to-send request against `https://gwapi.ourdex.com/{chain}/07541bf85df2072a9e0d0b2a964dc718`.

## Quick Start

Before building any request, collect these required inputs:

- `chain`: one of `bnbchain`, `solana`, `base`, `xlayer`, `ethereum`
- fixed `appId`: `07541bf85df2072a9e0d0b2a964dc718`
- entity input: token address, pool address, address list, or a filter query

Use this HTTP shape:

```http
POST https://gwapi.ourdex.com/{chain}/07541bf85df2072a9e0d0b2a964dc718
Content-Type: application/json
```

Use a normal JSON-RPC body:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "dex_status",
  "params": []
}
```

## Gateway Access

This skill is configured for a public read-only app that does not require JWT authentication.

- `chain`: `bnbchain`, `solana`, `base`, `xlayer`, or `ethereum`
- `appId`: always `07541bf85df2072a9e0d0b2a964dc718`

Gateway shape:

```http
POST https://gwapi.ourdex.com/{chain}/07541bf85df2072a9e0d0b2a964dc718
Content-Type: application/json
```

Access rules:

- Use HTTPS only.
- Treat `bnbchain` as the canonical chain name for BSC.
- Always use the fixed `appId` above in the path.
- Do not add `Authorization` for this skill's default app.
- Do not move `appId` into a custom header or query string.
- If the user asks how to call the gateway with `curl`, read [gateway-usage.md](./references/gateway-usage.md).
- If the user asks about JWT creation, explain that this skill's configured app does not need JWT and continue with the plain request format.

## Security

Request handling rules:

- Do not ask the user for JWTs, private keys, or auth headers for this app.
- Do not add `Authorization: Bearer ...` or other secret-bearing headers.
- Keep requests pointed at `https://gwapi.ourdex.com` only.
- Keep the fixed `appId` in the path and do not replace it unless the user explicitly asks to reconfigure the skill.
- This skill is read-only. Do not use provided credentials for `admin_*`, swap execution, or any write path.

## Scope

This skill is for read-oriented public `dex_*` RPC methods exposed by the UXUY DEX gateway.

Include:

- `dex_version`, `dex_status`, `dex_storage`
- `dex_getCoin`, `dex_getCoins`, `dex_coinQuery`
- `dex_getPool`, `dex_getPools`, `dex_poolQuery`
- `dex_getQuote`, `dex_getQuotes`
- `dex_getVolume`, `dex_getVolumes`
- `dex_aggQuery`, `dex_aggVolume`, `dex_aggTrader`
- `dex_ranking`
- `dex_txsQuery`

Do not use this skill for:

- `admin_*`
- swap execution flows such as `dex_swap`, `dex_swapV2`, `dex_updateSwap`

## Method Selection

Use this mapping when the user asks for data:

- Chain health or sync status: `dex_status`
- Storage status only: `dex_storage`
- Service version: `dex_version`
- One token metadata and current price: `dex_getCoin`
- Many tokens by address: `dex_getCoins`
- Paginated token list: `dex_coinQuery`
- One pool detail, reserves, and values: `dex_getPool`
- Many pools by address: `dex_getPools`
- Paginated pool list: `dex_poolQuery`
- One token summary quote over a time window: `dex_getQuote`
- Many token quotes over a time window: `dex_getQuotes`
- Aggregate token/pool/dex volume summary: `dex_getVolume` or `dex_getVolumes`
- Time series such as candles, fund flow, reserve ranking, router ranking: `dex_aggQuery`
- Volume time series for a pair or target bucket: `dex_aggVolume`
- Trader-count time series: `dex_aggTrader`
- Hot/gainer/loser/new/tvl rankings: `dex_ranking`
- Recent tx history for token or pool activity: `dex_txsQuery`

If the request is ambiguous, prefer the smallest read-only method that directly answers it.

## Query Rules

For methods that take a `FilterQuery`, use these defaults and limits:

- `page` is user-facing pagination; if omitted or `<= 0`, treat it as the first page
- `size` defaults to `30` and caps at `1440`
- batch address methods cap at `30` addresses
- `every` supports `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`, `1w`, `1M`, `1y`
- `rawData: "1"` disables beautified aggregation output; omit it for normal chart use

When the user asks for rankings, aggregations, volumes, or txs, read [rpc-reference.md](./references/rpc-reference.md) for valid `target` values before answering.

## Working Style

When using this skill:

1. Restate the exact gateway URL with the chosen chain and fixed app id.
2. Name the RPC method explicitly.
3. Show the params in JSON-RPC form.
4. If the user asked a business question like "查 24h 热门币", translate it to the underlying method and `target`.
5. Do not add an `Authorization` header unless the user explicitly says they are not using the default app.
6. If the user omitted the chain, ask only for the missing chain or entity input.
7. If examples conflict with the reference files in this skill or observed gateway behavior, trust the public RPC contract.

## Request Template

Use this cURL shape by default:

```bash
curl https://gwapi.ourdex.com/${CHAIN}/07541bf85df2072a9e0d0b2a964dc718 \
  -H 'Content-Type: application/json' \
  --data '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"dex_status",
    "params":[]
  }'
```

For more ready-to-send cURL examples, read [gateway-usage.md](./references/gateway-usage.md).

## Examples

Get chain status:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "dex_status",
  "params": []
}
```

Call URL:

```text
https://gwapi.ourdex.com/bnbchain/07541bf85df2072a9e0d0b2a964dc718
```

Get one token:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "dex_getCoin",
  "params": ["0x1234567890abcdef1234567890abcdef12345678"]
}
```

Get one token's 24h quote summary:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "dex_getQuote",
  "params": [
    "0x1234567890abcdef1234567890abcdef12345678",
    {
      "start": "-24h",
      "target": "token"
    }
  ]
}
```

Get 24h hot token ranking:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "dex_ranking",
  "params": [
    {
      "target": "token/hot",
      "start": "-24h",
      "size": 10
    }
  ]
}
```

Get token candle series:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "dex_aggQuery",
  "params": [
    "0x1234567890abcdef1234567890abcdef12345678",
    {
      "target": "token/quote",
      "start": "-24h",
      "every": "1h",
      "size": 24
    }
  ]
}
```

Get recent token swap txs:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "dex_txsQuery",
  "params": [
    "0x1234567890abcdef1234567890abcdef12345678",
    {
      "target": "token/swap",
      "page": 1,
      "size": 20
    }
  ]
}
```
