# UXUY DEX RPC Reference

Use this file only when the user needs exact `target` values, limits, or method-specific details.

## Gateway

- Base host: `https://gwapi.ourdex.com`
- Path: `/{chain}/{appId}`
- Supported chains: `bnbchain`, `solana`, `base`, `xlayer`, `ethereum`
- Header: `Authorization: Bearer <jwt token>`

## Core Methods

- `dex_version()`
- `dex_status()`
- `dex_storage()`
- `dex_getCoin(address)`
- `dex_getCoins(address[])`
- `dex_coinQuery(FilterQuery)`
- `dex_getPool(address)`
- `dex_getPools(address[])`
- `dex_poolQuery(FilterQuery)`
- `dex_getQuote(address, FilterQuery)`
- `dex_getQuotes(address[], FilterQuery)`
- `dex_getVolume(address, FilterQuery)`
- `dex_getVolumes(address[], FilterQuery)`
- `dex_aggQuery(address, FilterQuery)`
- `dex_aggVolume(address0, address1, FilterQuery)`
- `dex_aggTrader(address, FilterQuery)`
- `dex_ranking(FilterQuery)`
- `dex_txsQuery(address, FilterQuery)`

## FilterQuery Rules

- `page <= 0` becomes the first page
- `size <= 0` becomes `30`
- `size > 1440` becomes `1440`
- `every` accepts:
  - `1m`, `1min`
  - `5m`, `5min`
  - `15m`, `15min`
  - `30m`, `30min`
  - `1h`, `1hour`
  - `4h`, `4hour`
  - `1d`, `1day`, `1date`
  - `1w`, `1week`
  - `1M`, `1month`, `1mon`
  - `1y`, `1year`
- `rawData: "1"` means non-beautified raw aggregation output
- multi-address methods reject more than `30` addresses

## Ranking Targets

`dex_ranking` supports these code-backed targets:

- `token/hot`
- `token/gainer`
- `token/loser`
- `token/tvl`
- `pool/new`
- `pool/hot`
- `factory/hot`
- `router/hot`
- `amm/hot`
- `dex/hot`

Some repo docs mention extra ranking targets. If they are not reflected in this skill's validated public RPC reference, do not present them as guaranteed.

## Volume Targets

`dex_getVolume` and `dex_getVolumes`:

- `token`
- `pool` or `pools`
- `amm` or `factory`
- `dex` or `router`

## Aggregation Targets

`dex_aggQuery` supports:

- `token/quote`
- `token/fundmap`
- `token/poolreserve`
- `token/poolranking`
- `token/routerranking`
- `token/factoryranking`
- `token/dexranking`
- `token/ammranking`

`dex_aggVolume` supports:

- token-pair or bucketed targets backed by volume constants in code
- prefer using it only when the user clearly wants a time series rather than one summary number

`dex_aggTrader` supports:

- `token`
- `pool` or `pools`
- `amm` or `factory`
- `dex` or `router`

## Transaction Targets

`dex_txsQuery` delegates target matching to the tx index search. Repo docs describe common values:

- `token/swap`
- `token/add`
- `token/remove`
- `pool/swap`
- `pool/add`
- `pool/remove`
- `dex/swap`
- `dex/add`
- `dex/remove`

Present these as the common supported targets for tx history queries.

## Response Shapes

- `dex_getCoin` returns a `RpcCoin` with token metadata, current USD price, and timestamp.
- `dex_getPool` returns pool metadata, tokens, reserves, values, birth time, and extra fields.
- `dex_getQuote` returns one `RpcQuote` with OHLC, change, volume, traders, liquidity, tx count, and market cap when available.
- `dex_getVolume` returns either `rpcVolume` or `rpcValue` depending on target class.
- `dex_txsQuery` returns `RpcTransaction[]` sorted by newest first.
- `dex_status` returns chain metadata plus latest and updated block heights.

## Practical Defaults

- For "24h quote summary", use `dex_getQuote` with `{"start":"-24h","target":"token"}`.
- For "24h candles", use `dex_aggQuery` with `{"target":"token/quote","start":"-24h","every":"1h"}`.
- For "hot list", use `dex_ranking` with `{"target":"token/hot","start":"-24h","size":10}`.
- For "recent trades", use `dex_txsQuery` with a tx target and a modest page size such as `20`.
