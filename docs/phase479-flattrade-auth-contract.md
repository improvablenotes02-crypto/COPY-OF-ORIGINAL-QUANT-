# Phase 479 - Flattrade token-exchange signing contract

Flattrade's published Python token-generator uses a SHA-256 digest over the exact concatenation:

`api_key + request_code + api_secret`

and posts the digest as `api_secret` to the token endpoint:

`https://authapi.flattrade.in/trade/apitoken`

QuantEngine now has a pure/offline helper that builds this request payload and tests the exact byte-level contract. It does not make a network request, persist credentials, implement the browser login callback, parse/store session tokens, or connect a Flattrade broker adapter.

The helper must be integrated only through a future local-only authentication flow. Never print the API secret, request code, digest, or returned session token. The current Flattrade support status remains NOT IMPLEMENTED.
