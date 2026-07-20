# giulia_gateway

LLM Gateway — a FastAPI service that bridges the Cursor IDE to Vertex AI
models (Claude, Gemini) via LiteLLM, with OpenAI passthrough support.

## Configuration

All environment-specific values are read from environment variables at
startup. See `giulia_gateway/app.py` and `litellm-config.yaml` for details.

### Required environment variables

| Variable | Description |
|---|---|
| `VERTEX_PROJECT` | GCP project ID (Vertex AI calls and Cloud Logging trace correlation) |

### Optional environment variables

| Variable | Default | Description |
|---|---|---|
| `GATEWAY_API_KEY` | _(none)_ | Static API key accepted without a DB lookup; when set, all DB variables below are ignored |
| `OPENAI_API_KEY` | _(none)_ | Enables OpenAI model passthrough |
| `GOOGLE_CLOUD_PROJECT` | `VERTEX_PROJECT` | Override project ID for Cloud Logging |
| `LITELLM_CONFIG` | `/app/litellm-config.yaml` | Path to model config |
| `GATEWAY_MODEL_PREFIX` | _(empty)_ | Optional extra namespace prepended to every model name (see below) |

## Model naming

The model names in `litellm-config.yaml` (e.g. `claude-4.8-opus-thinking-high`)
are identical to Cursor's built-in model slugs. To avoid shadowing them, the
gateway rewrites each configured model to a **public name** at load time (by
swapping the family word for a codename) and exposes only those via
`/v1/models`. The rest of the name — version and variant suffix — is unchanged.

Codenames (`_MODEL_ALIASES` in `app.py`):

- `claude` → `giulia`
- `opus` → `leonardo`
- `sonnet` → `raptor`

Register these public names in Cursor, e.g.:

```
giulia-4.8-leonardo-thinking-high      # was claude-4.8-opus-thinking-high
giulia-raptor-5-thinking-high          # was claude-sonnet-5-thinking-high
gemini-3-pro-preview                   # unchanged (no codename)
```

Incoming requests are resolved leniently, so all of the following map to the
same deployment and keep working:

- the public codename name — `giulia-4.8-leonardo-thinking-high`
- the bare canonical name — `claude-4.8-opus-thinking-high`
- the legacy dashed-version name — `claude-opus-4-8-thinking-high`

Families without a codename (e.g. Gemini) keep their original names and so still
overlap Cursor's built-ins. Set `GATEWAY_MODEL_PREFIX` (e.g. `giulia-`) to also
prepend a namespace to every model if you need those distinct too.

OpenAI passthrough models (`gpt-*`, `o1-*`, …) are forwarded upstream unchanged.

#### Cloud SQL variables (required when `GATEWAY_API_KEY` is not set)

| Variable | Default | Description |
|---|---|---|
| `DB_INSTANCE` | _(none)_ | Cloud SQL instance connection name (`project:region:instance`) |
| `DB_USER` | _(none)_ | IAM database user (e.g. `my-sa@my-project.iam`) |
| `DB_NAME` | `brain` | Database name |
| `DB_IP_TYPE` | `private` | `private` or `public` for Cloud SQL |

## Running locally

```bash
export VERTEX_PROJECT=my-project
export DB_INSTANCE=my-project:region:instance
export DB_USER=my-user@my-project.iam
export CLOUD_SQL_PROXY_HOST=127.0.0.1
uvicorn giulia_gateway.app:app --host 0.0.0.0 --port 8080 --reload
```
