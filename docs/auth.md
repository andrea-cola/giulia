# Auth Layer

`giulia.agents.auth` implements **Zero Trust, audience-bound JWT authentication**
for agent-to-agent calls.

---

## Overview

```
Caller                        OAuth service              Target agent
  │                                │                          │
  │ POST /token                    │                          │
  │ (client_id, secret, audience)  │                          │
  │──────────────────────────────►│                          │
  │                                │ mint_token(sub, aud, …) │
  │                                │ sign_jwt(payload)        │
  │                                │ ← KMS RS256 signature    │
  │ ◄──────────────────────────────│                          │
  │  {access_token, expires_in}    │                          │
  │                                                           │
  │ POST /a2a  Authorization: Bearer <token>                  │
  │──────────────────────────────────────────────────────────►│
  │                                        verify_jwt(token)  │
  │                                        (checks aud, exp,  │
  │                                         iss, signature)   │
```

---

## Public API

### `mint_token`

```python
from giulia.agents.auth.token_mint import mint_token

token, expires_in = mint_token(
    sub="client-id",
    client_name="my-service",
    scopes=["agent:invoke"],
    audience="urn:agent:acme:public:sophia",
    ttl=60,
)
```

Produces a short-lived, audience-bound RS256 JWT.
The `ttl` is capped at `max_ttl` (default 300 s).

**Claims emitted**

| Claim | Value |
|-------|-------|
| `sub` | caller `client_id` |
| `iss` | `"giulia-oauth"` (configurable) |
| `aud` | target agent URN |
| `iat` / `exp` | issued-at and expiry |
| `scope` | space-separated scope string |
| `jti` | random UUID (prevents replay) |
| `client_name` | human-readable caller |
| `delegation_chain` | list of agent URNs (optional) |

---

### `mint_exchanged_token` (RFC 8693)

Used when an intermediate agent needs to call a downstream agent on behalf
of the original caller:

```python
from giulia.agents.auth.token_mint import mint_exchanged_token

new_token, expires_in = mint_exchanged_token(
    original_payload=inbound_jwt_claims,
    new_audience="urn:agent:acme:public:downstream",
    acting_as="urn:agent:acme:internal:broker",
)
```

The `delegation_chain` is extended: `[original_sub, …, acting_as]`.

---

### `sign_jwt` / `verify_jwt`

Low-level primitives. Both route through the configured `KmsSigningProvider`
(default: `GcpKmsProvider`). Swap the provider before startup for tests:

```python
from giulia.providers.registry import set_kms
from my_package import MyTestKms

set_kms(MyTestKms())
```

---

### `JWTValidationError`

Raised by `verify_jwt` on any failure (expired, bad signature, wrong audience,
wrong issuer, malformed token). Always catch this, never `Exception`, in
middleware.

---

## API Key authentication

`giulia.agents.auth.api_keys` provides `validate_api_key` for services that
prefer symmetric API key auth (e.g. internal tools). Keys are stored in the
database and checked with a constant-time comparison.

---

## Google OAuth

`giulia.agents.auth.google_oauth` handles inbound Google OAuth 2.0 tokens
(ID tokens). It verifies the token against Google's JWKS endpoint and returns
the decoded claims.
