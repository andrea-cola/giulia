# giulia_gateway

LLM Gateway — a FastAPI service that bridges the Cursor IDE to Vertex AI
models (Claude, Gemini) via LiteLLM, with OpenAI passthrough support.

## Configuration

All environment-specific values are read from environment variables at
startup. See `giulia_gateway/app.py` and `litellm-config.yaml` for details.

### Required environment variables

| Variable | Description |
|---|---|
| `VERTEX_PROJECT` | GCP project ID for Vertex AI calls |
| `DB_INSTANCE` | Cloud SQL instance connection name |
| `DB_USER` | IAM database user |
| `DB_NAME` | Database name (default: `brain`) |
| `GOOGLE_CLOUD_PROJECT` | GCP project for Cloud Logging trace correlation |

### Optional environment variables

| Variable | Default | Description |
|---|---|---|
| `GATEWAY_API_KEY` | _(none)_ | Static API key accepted without a DB lookup |
| `OPENAI_API_KEY` | _(none)_ | Enables OpenAI model passthrough |
| `DB_IP_TYPE` | `private` | `private` or `public` for Cloud SQL |
| `LITELLM_CONFIG` | `/app/litellm-config.yaml` | Path to model config |

## Running locally

```bash
export VERTEX_PROJECT=my-project
export DB_INSTANCE=my-project:region:instance
export DB_USER=my-user@my-project.iam
export CLOUD_SQL_PROXY_HOST=127.0.0.1
uvicorn giulia_gateway.app:app --host 0.0.0.0 --port 8080 --reload
```
