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
