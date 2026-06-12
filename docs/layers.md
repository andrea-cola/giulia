# Giulia — Layer Reference

Giulia is structured around **layers**, each owning a distinct slice of the
agent lifecycle. Every layer lives under `giulia/agents/<layer>/` and exposes
a clean `__init__.py` re-export surface.

---

## Layer Map

| # | Layer | Package path | Key public symbols |
|---|-------|--------------|--------------------|
| 1 | **Core** | `giulia.agents.core` | `GiuliaAgent`, `AgentYAMLConfig`, `AgentContext`, `GiuliaConfig` |
| 2 | **Auth** | `giulia.agents.auth` | `sign_jwt`, `verify_jwt`, `mint_token`, `mint_exchanged_token`, `JWTValidationError` |
| 3 | **A2A** | `giulia.agents.a2a` | `to_a2a_giulia`, `A2AAgentFactory` |
| 4 | **Delegation** | `giulia.agents.delegation` | `DelegationHandler`, `RedisDelegationBackend` |
| 5 | **Orchestration** | `giulia.agents.orchestration` | `ActivityLog`, `ApprovalsService`, `record_heartbeat` |
| 6 | **Registry client** | `giulia.agents.registry_client` | `register_private_agent`, `build_agent_card`, `start_heartbeat` |
| 7 | **Services** | `giulia.agents.services` | `ArtifactService`, `McpFactory`, `SkillLoader` |
| 8 | **Push notifications** | `giulia.agents.push_notifications` | `PushNotificationClient`, `PushNotificationHandler` |
| 9 | **Google Chat** | `giulia.agents.google_chat` | `GoogleChatClient`, `GoogleChatWebhookHandler` |
| 10 | **Middlewares** | `giulia.agents.middlewares` | `ApiKeyMiddleware`, `RequestLoggingMiddleware`, `StripPrefixMiddleware` |
| 11 | **Utils** | `giulia.agents.utils` | `urn_to_slug`, `urn_to_python_identifier`, `TTLCache` |
| 12 | **Providers** | `giulia.providers` | `GcpKmsProvider`, `CloudSqlDatabase`, `RedisAuth`, `SecretManager` |

---

## Provider / Infrastructure Layer

`giulia.providers` contains concrete infrastructure adapters. All adapters
implement an abstract interface so they can be swapped for testing or
non-GCP deployments.

| Module | Interface | Default impl |
|--------|-----------|--------------|
| `kms` | `KmsProvider` / `KmsSigningProvider` | `GcpKmsProvider` |
| `database` | `DatabaseProvider` | `CloudSqlDatabase` |
| `redis_auth` | — | IAM-authenticated Redis client |
| `secrets` | `SecretProvider` | `GcpSecretManager` |
| `registry` | provider accessors | singleton registry (get_kms, get_db, …) |

---

## Registry (server-side)

`giulia.registry` is the server-side agent catalogue — intended to be deployed
as a standalone service (see `dw-ai-brain/api`). It is **not** required to run
an agent; the client-side equivalent is `giulia.agents.registry_client`.

| Module | Purpose |
|--------|---------|
| `models` | Pydantic models for agent records |
| `store` | Abstract store interface |
| `cloudsql_store` | Cloud SQL implementation |
| `embeddings` | Semantic search via vector embeddings |
| `registry` | High-level registry service |
| `tools` | ADK tools that wrap the registry for agent use |

---

## Adding a New Layer

1. Create `giulia/agents/<layer>/` with an `__init__.py` that re-exports the
   public API.
2. Add at least one test file: `tests/test_<layer>.py`.
3. Update this file with the layer's row and public symbols.
