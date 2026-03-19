# UXUY DEX Authentication Reference

Use this file when the user asks how to create a JWT, debug authentication failures, or understand what the gateway validates.

## Gateway Contract

- Base host: `https://gwapi.ourdex.com`
- Path shape: `/{chain}/{appId}`
- Header: `Authorization: Bearer <jwt token>`
- Supported chains: `bnbchain`, `solana`, `base`, `xlayer`, `ethereum`

## What The Server Validates

Code-backed behavior in the repo:

- The HTTP path is parsed as `/{chain}/{appId}`.
- The gateway validates the app using the path `appId`.
- The only supported authenticated public flow is Bearer JWT.
- JWT validation looks up the registered public key by JWT header `jti`.
- Accepted signing algorithms are `RS256` and `ES256`.
- After signature verification, normal JWT claim validation runs, so `exp` must still be valid.

## Required JWT Inputs

To mint a token, collect:

- `appId`
- `chain`
- `jwtId`
- `jwtIssuer`
- `alg`: `RS256` or `ES256`
- private key matching the app's registered public key

## Accepted User Input Formats

Users can provide authentication material in either of these formats.

Ready JWT:

```yaml
chain: bnbchain
appId: 4c638fe0acf6492ca97e8da367952b31
jwtToken: eyJhbGciOiJSUzI1NiIs...
```

JWT minting inputs:

```yaml
chain: bnbchain
appId: 4c638fe0acf6492ca97e8da367952b31
jwtId: 23c7bc0aa92ce8cc5d24d0cd416f5590
jwtIssuer: 0xdex.io
alg: RS256
privateKeyPem: |
  -----BEGIN RSA PRIVATE KEY-----
  ...
  -----END RSA PRIVATE KEY-----
```

Private-key file content is also acceptable as plain PEM text:

```pem
-----BEGIN RSA PRIVATE KEY-----
...
-----END RSA PRIVATE KEY-----
```

Handling rules:

- If a ready JWT is provided, do not ask for the private key unless the user explicitly wants to mint a new token.
- If minting inputs are incomplete, ask only for the missing fields.
- When the user pastes PEM content, treat it as secret material and never echo it back verbatim.

## JWT Shape

Header:

```json
{
  "alg": "RS256",
  "typ": "JWT",
  "jti": "23c7bc0aa92ce8cc5d24d0cd416f5590"
}
```

Claims:

```json
{
  "iss": "0xdex.io",
  "jti": "23c7bc0aa92ce8cc5d24d0cd416f5590",
  "exp": 1710000300,
  "ts": 1710000000
}
```

Notes:

- Keep `jti` in the JWT header aligned with the registered JWT key id.
- Keep the `jti` claim aligned with the same JWT key id.
- Use a short expiry window.
- `ts` is the current Unix timestamp in seconds.

## Go Example

This follows the public gateway JWT flow described in this skill.

```go
claims := jwt.MapClaims{
  "iss": jwtIssuer,
  "jti": jwtId,
  "exp": time.Now().Add(5 * time.Minute).Unix(),
  "ts":  time.Now().Unix(),
}

tokenClaims := jwt.NewWithClaims(jwt.SigningMethodRS256, claims)
tokenClaims.Header["jti"] = jwtId
token, err := tokenClaims.SignedString(privateKey)
```

Then call:

```http
POST https://gwapi.ourdex.com/bnbchain/{appId}
Authorization: Bearer <jwt token>
Content-Type: application/json
```

With JSON-RPC body:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "dex_getCoin",
  "params": ["0x1234567890abcdef1234567890abcdef12345678"]
}
```

## curl Examples

Use a ready JWT:

```bash
curl https://gwapi.ourdex.com/bnbchain/${APP_ID} \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${JWT_TOKEN}" \
  --data '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"dex_getCoin",
    "params":["0x1234567890abcdef1234567890abcdef12345678"]
  }'
```

Use a ready JWT for a 24h quote:

```bash
curl https://gwapi.ourdex.com/bnbchain/${APP_ID} \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${JWT_TOKEN}" \
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

Mint a JWT locally with OpenSSL and Python, then call the gateway:

```bash
HEADER_B64=$(printf '%s' '{"alg":"RS256","typ":"JWT","jti":"'"${JWT_ID}"'"}' | openssl base64 -A | tr '+/' '-_' | tr -d '=')
NOW=$(date +%s)
EXP=$((NOW + 300))
PAYLOAD_B64=$(printf '%s' '{"iss":"'"${JWT_ISSUER}"'","jti":"'"${JWT_ID}"'","exp":'"${EXP}"',"ts":'"${NOW}"'}' | openssl base64 -A | tr '+/' '-_' | tr -d '=')
SIGN_INPUT="${HEADER_B64}.${PAYLOAD_B64}"
SIG_B64=$(printf '%s' "${SIGN_INPUT}" | openssl dgst -sha256 -sign "${PRIVATE_KEY_FILE}" -binary | openssl base64 -A | tr '+/' '-_' | tr -d '=')
JWT_TOKEN="${SIGN_INPUT}.${SIG_B64}"

curl https://gwapi.ourdex.com/bnbchain/${APP_ID} \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${JWT_TOKEN}" \
  --data '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"dex_status",
    "params":[]
  }'
```

Notes for the shell example:

- This example is for `RS256`.
- `${PRIVATE_KEY_FILE}` should point to a PEM private key file.
- Keep the expiry short, such as 5 minutes.
- Do not print or persist `${JWT_TOKEN}` unless the user explicitly asks.

## Failure Checklist

If authentication fails, check these first:

- `chain` is one of the supported chain names
- URL path is exactly `/{chain}/{appId}`
- `Authorization` header starts with `Bearer `
- JWT header `jti` matches a registered key id
- signing algorithm matches the registered public key type
- token is not expired
- token was signed by the correct private key

## Security Rules

- Never print full private keys or full JWTs in answers.
- Never suggest putting secrets into query strings.
- Never suggest non-HTTPS endpoints.
- Prefer ephemeral token generation over writing tokens to disk.
