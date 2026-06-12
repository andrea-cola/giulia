# giulia-sdk

> **Status: planned**

Lightweight, dependency-free SDK exposing the **layer interfaces** (Protocol
classes) and shared types for the `giulia` agent framework.

Consumers implement these interfaces to plug custom auth, registry, transport,
or trust layers into any `giulia`-based agent — without depending on the full
`giulia` package.

---

## Planned layer interfaces

| Interface | Description |
|-----------|-------------|
| `Auth` | Token minting and verification |
| `Registry` | Agent registration and discovery |
| `Transport` | Message delivery between agents |
| `Trust` | Reputation scoring and Sybil resistance |
| `Identity` | DID / key-based agent identity |
| `KmsProvider` | Key management and signing |
| `SecretProvider` | Secret retrieval |
| `DatabaseProvider` | Database connection abstraction |

## Planned types

```python
from giulia_sdk.types import AgentId, AgentUrn, Scope, Token, Money
from giulia_sdk.layers.auth import Auth
from giulia_sdk.layers.registry import Registry
```

## Design goals

- **Zero heavy dependencies** — only `pydantic` for models.
- **Structural typing** — all interfaces use `typing.Protocol`; no inheritance required.
- **Independently versioned** — can be pinned separately from `giulia`.

## Installation (future)

```bash
pip install giulia-sdk
```

## Contributing

See the root [CONTRIBUTING.md](../../CONTRIBUTING.md) and the workspace
[Makefile](../../Makefile) for development setup.
