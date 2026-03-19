---
name: uxuy-dex
description: Use this skill when the user wants to query UXUY DEX market data through the authenticated public RPC gateway, especially token, pool, quote, volume, ranking, transaction, or chain status data on bnbchain, solana, base, xlayer, or ethereum.
---

# UXUY DEX

Use this skill to map a market-data question to the correct UXUY DEX JSON-RPC method and produce a ready-to-send request against `https://gwapi.ourdex.com/{chain}/{appId}`.

## Quick Start

Before building any request, collect these required inputs:

- `chain`: one of `bnbchain`, `solana`, `base`, `xlayer`, `ethereum`
- `appId`: part of the URL path
- `jwt token`: send as `Authorization: Bearer <jwt token>`
- entity input: token address, pool address, address list, or a filter query

Use this HTTP shape:

```http
POST https://gwapi.ourdex.com/{chain}/{appId}
Content-Type: application/json
Authorization: Bearer <jwt token>
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

## Authentication

Required inputs for authenticated public RPC:

- `chain`: `bnbchain`, `solana`, `base`, `xlayer`, or `ethereum`
- `appId`: part of the gateway path, not a header
- `jwt token`: send only as `Authorization: Bearer <jwt token>`

Gateway shape:

```http
POST https://gwapi.ourdex.com/{chain}/{appId}
Content-Type: application/json
Authorization: Bearer <jwt token>
```

Authentication rules:

- Use HTTPS only.
- Treat `bnbchain` as the canonical chain name for BSC.
- Do not move `appId` into a custom header or query string.
- Do not use Basic auth or app secret auth for this public gateway flow.
- If the user asks how to mint a token, share a token, or use `curl`, read [authentication.md](./references/authentication.md).
- If the user omits auth inputs, ask only for the missing values.

## Security

Credential handling rules:

- Users may provide either a ready JWT or JWT minting inputs such as `jwtId`, `jwtIssuer`, `alg`, and a private key.
- Never print a full JWT token, private key, or the filesystem location of a private key.
- When echoing credentials back, mask them:
  - `appId`: show a short hash-style preview such as `4c638f...2b31`
  - `jwtId`: show a short hash-style preview such as `23c7bc...5590`
  - `jwt token`: show only a short prefix and suffix such as `eyJhb...abc123`
  - private key: never display it; describe only the algorithm or fingerprint if needed
- Never store credentials in repo files, commits, examples, or long-lived notes unless the user explicitly asks for that exact path.
- Never send UXUY credentials to any host other than `https://gwapi.ourdex.com`.
- Never suggest unsupported auth modes such as `Authorization: Basic`, query-string tokens, or custom `appid` auth headers.
- This skill is read-only. Do not use provided credentials for `admin_*`, swap execution, or any write path.

## Scope

This skill is for read-oriented public `dex_*` RPC methods exposed by the authenticated UXUY DEX gateway.

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

1. Restate the exact gateway URL with the chosen chain and app id.
2. Name the RPC method explicitly.
3. Show the params in JSON-RPC form.
4. If the user asked a business question like "查 24h 热门币", translate it to the underlying method and `target`.
5. Mask any credential material that appears in the answer.
6. If the user omitted required auth or chain inputs, ask only for the missing values.
7. If examples conflict with the reference files in this skill or observed gateway behavior, trust the public RPC contract.

## JWT Token Creation

UXUY DEX JWTs for this gateway are asymmetric JWTs, not HMAC tokens.

- Supported signing algorithms: `RS256`, `ES256`
- Header must include `jti`, and it must match a registered JWT key id for the app
- Claims should include:
  - `iss`: the JWT issuer name
  - `jti`: the JWT key id
  - `exp`: a near-term expiry
  - `ts`: current Unix timestamp in seconds
- Sign with the matching private key, then send the token as a Bearer token

Use this high-level workflow:

1. Pick `RS256` or `ES256` to match the registered public key.
2. Build claims with `iss`, `jti`, `exp`, and `ts`.
3. Set JWT header `jti` to the same JWT key id.
4. Sign with the private key.
5. Send `Authorization: Bearer <jwt token>` to `https://gwapi.ourdex.com/{chain}/{appId}`.

For code-backed details and a Go example, read [authentication.md](./references/authentication.md).

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
