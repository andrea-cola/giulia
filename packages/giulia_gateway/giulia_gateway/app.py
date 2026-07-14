"""
FastAPI app for the LLM Gateway (runs on Cloud Run).

Uses LiteLLM in-process via acompletion(); no LiteLLM HTTP subprocess.
OpenAI models (gpt-*, o1-*, o3-*, ...) are forwarded directly to the
OpenAI API so they work exactly as in standard Cursor mode.
API keys are verified against a Cloud SQL PostgreSQL database via the
Cloud SQL Python Connector (IAM auth, no sidecar needed).
"""

import asyncio
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, cast

import httpx
import yaml
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from litellm.router import Router

from giulia_gateway.api_keys import close_pool as _close_key_pool
from giulia_gateway.api_keys import init_pool as _init_key_pool
from giulia_gateway.api_keys import verify_key
from giulia_gateway.logging_config import get_logger, setup_logging
from giulia_gateway.request_cleaner import (
    CONDENSATION_MODEL,
    build_condensation_request,
    build_generation_request,
    context_limit_for_model,
    inject_draft_into_messages,
    process_request_body,
    split_for_condensation,
)

setup_logging()
logger = get_logger("app")

security = HTTPBearer(auto_error=False)
app = FastAPI(title="Giulia LLM Gateway")

OPENAI_API_BASE = "https://api.openai.com/v1"
OPENAI_PASSTHROUGH_PREFIXES = (
    "gpt-",
    "o1-",
    "o3-",
    "o4-",
    "o1",
    "o3",
    "o4",
    "chatgpt-",
    "dall-e",
    "tts-",
    "whisper",
    "gpt3",
    "gpt4",
    "gpt5",
    "text-embedding",
    "text-moderation",
)

_openai_api_key: str = ""
_openai_client: httpx.AsyncClient | None = None

_config: dict[str, Any] = {}
_model_names: set[str] = set()
_router: Router | None = None

# Default variant kwargs for Claude Opus models (use "enabled" thinking API).
_MODEL_VARIANT_KWARGS: dict[str, dict] = {
    "-thinking-max": {
        "thinking": {"type": "enabled", "budget_tokens": 32768},
        "reasoning_effort": "max",
    },
    "-thinking-high": {
        "thinking": {"type": "enabled", "budget_tokens": 16384},
        "reasoning_effort": "high",
    },
    "-thinking": {
        "thinking": {"type": "enabled", "budget_tokens": 16384},
        "reasoning_effort": "high",
    },
    "-xhigh": {
        "thinking": {"type": "enabled", "budget_tokens": 65536},
        "reasoning_effort": "max",
    },
    "-max": {
        "reasoning_effort": "max",
    },
    "-high": {},
}

# Newer Claude models on Vertex AI (claude-opus-4-8+, claude-sonnet-5+) use the
# "adaptive" thinking API with output_config.effort instead of the "enabled" API
# with budget_tokens that older Opus models use.
_ADAPTIVE_VARIANT_KWARGS: dict[str, dict] = {
    "-thinking-max": {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "max"},
    },
    "-thinking-high": {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    },
    "-thinking": {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    },
    "-xhigh": {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "max"},
    },
    "-max": {
        "output_config": {"effort": "max"},
    },
    "-high": {},
    "-medium": {},
}

# Map model-name prefixes (canonical form) to their variant-kwargs table.
# Prefixes are matched in order; first match wins.
_MODEL_FAMILY_VARIANT_KWARGS: list[tuple[str, dict[str, dict]]] = [
    ("claude-4.8-opus", _ADAPTIVE_VARIANT_KWARGS),
    ("claude-sonnet-5", _ADAPTIVE_VARIANT_KWARGS),
]

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _expand_env_vars(obj):
    """Recursively expand ${VAR} placeholders in strings within a parsed YAML structure."""
    if isinstance(obj, str):
        return _ENV_VAR_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), obj)
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(item) for item in obj]
    return obj


def _is_openai_model(model: str) -> bool:
    """Return True if the model should be forwarded to the OpenAI API."""
    m = model.lower()
    return m.startswith(OPENAI_PASSTHROUGH_PREFIXES)


def _load_config() -> None:
    """Load litellm-config.yaml and initialise the LiteLLM Router.

    Environment variable placeholders (``${VAR}``) in the YAML are expanded
    at load time so deployment-specific values (e.g. ``VERTEX_PROJECT``) can
    be injected without baking them into the config file.
    """
    global _config, _model_names, _router
    config_path = os.environ.get(
        "LITELLM_CONFIG",
        os.environ.get("CONFIG_PATH", "/app/litellm-config.yaml"),
    )
    path = Path(config_path)

    if not path.exists():
        for candidate in [
            Path.cwd() / "litellm-config.yaml",
            Path(__file__).parent / "litellm-config.yaml",
        ]:
            if candidate.exists():
                path = candidate
                break

    if not path.exists():
        logger.warning(
            "No config file found at %s; model_list will be empty", config_path
        )
        _config = {}
        _model_names = set()
        return

    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    _config = cast(dict[str, Any], _expand_env_vars(raw))
    model_list = _config.get("model_list", [])
    _model_names = {e["model_name"] for e in model_list if e.get("model_name")}

    _router = Router(model_list=model_list, routing_strategy="simple-shuffle")
    deployment_count = len(model_list)
    logger.info(
        "Loaded config: %d model names, %d deployments",
        len(_model_names),
        deployment_count,
    )


@app.on_event("startup")
async def startup():
    """Initializes config, API-key pool, and OpenAI passthrough client."""
    global _openai_api_key, _openai_client
    _load_config()
    if _GATEWAY_API_KEY:
        logger.info("GATEWAY_API_KEY is set — skipping Cloud SQL API-key pool")
    else:
        await _init_key_pool()
    _openai_api_key = os.environ.get("OPENAI_API_KEY", "")
    if _openai_api_key:
        _openai_client = httpx.AsyncClient(
            base_url=OPENAI_API_BASE,
            timeout=httpx.Timeout(300, connect=10),
        )
        logger.info("OpenAI passthrough enabled (API key set)")
    else:
        logger.warning("OPENAI_API_KEY not set — OpenAI model passthrough disabled")


@app.on_event("shutdown")
async def shutdown():
    if not _GATEWAY_API_KEY:
        await _close_key_pool()


_GATEWAY_API_KEY: str = os.environ.get("GATEWAY_API_KEY", "").strip()


async def _verify_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    """Verify the incoming HTTP Bearer token.

    If GATEWAY_API_KEY is set and the token matches it, access is granted
    immediately without a database round-trip.  Otherwise the key is verified
    against the Cloud SQL api_keys table.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing API key")
    key = credentials.credentials
    if _GATEWAY_API_KEY and key == _GATEWAY_API_KEY:
        return key
    if not await verify_key(key):
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    return key


def _normalize_model_name(model_name: str) -> str:
    """Translate legacy ``claude-opus-{ver}-{variant}`` names to the canonical
    ``claude-{ver}-opus-{variant}`` format used in the config.

    Cursor (and older clients) send names like ``claude-opus-4-8-thinking-high``
    where the version uses dashes (``4-8``).  The gateway config uses dots
    (``claude-4.8-opus-thinking-high``), so we need to rewrite the name.
    """
    if not model_name.startswith("claude-opus-"):
        return model_name
    rest = model_name[len("claude-opus-") :]
    # Strip any known variant suffix so the remainder is the version string.
    suffix = ""
    for s in _MODEL_VARIANT_KWARGS:
        if rest.endswith(s):
            suffix = s
            rest = rest[: -len(s)]
            break
    # ``rest`` is now the version part, e.g. ``4-8`` or ``4.8``.
    # Normalise dash-separated digits to dot-separated (``4-8`` → ``4.8``).
    version = re.sub(r"^(\d+)-(\d+)$", r"\1.\2", rest)
    return f"claude-{version}-opus{suffix}"


def _resolve_model_name(model_name: str) -> str:
    """Resolve a possibly-suffixed model name to a configured model name."""
    if model_name in _model_names:
        return model_name

    normalized = _normalize_model_name(model_name)
    if normalized != model_name and normalized in _model_names:
        return normalized

    for suffix in _MODEL_VARIANT_KWARGS:
        if normalized.endswith(suffix):
            base = normalized[: -len(suffix)]
            if base in _model_names:
                return base
        if model_name.endswith(suffix):
            base = model_name[: -len(suffix)]
            if base in _model_names:
                return base
    return model_name


def _variant_kwargs(model_name: str) -> dict:
    """Return extra litellm kwargs for a model variant suffix.

    Looks up the appropriate variant table based on the model family first,
    then falls back to the default (Opus-style) table.
    """
    # Resolve the canonical name so family matching works even for legacy names.
    canonical = _normalize_model_name(model_name)
    table = _MODEL_VARIANT_KWARGS
    for prefix, family_table in _MODEL_FAMILY_VARIANT_KWARGS:
        if canonical.startswith(prefix):
            table = family_table
            break
    for suffix, kw in table.items():
        if canonical.endswith(suffix) or model_name.endswith(suffix):
            return dict(kw)
    return {}


@app.get("/health")
@app.get("/gateway/llm/health")
async def health():
    """Simple health check endpoint."""
    return {"status": "healthy", "service": "giulia-gateway"}


@app.get("/v1/models")
@app.get("/models")
@app.get("/gateway/llm/v1/models")
@app.get("/gateway/llm/models")
async def list_models():
    """Return the list of available models."""
    models = [
        {"id": name, "object": "model", "created": 1677610602, "owned_by": "anthropic"}
        for name in sorted(_model_names)
    ]
    return {"object": "list", "data": models}


async def _stream_chunks(response):
    """Yield SSE lines from a LiteLLM async stream."""
    async for chunk in response:
        try:
            if hasattr(chunk, "model_dump"):
                obj = chunk.model_dump(exclude_none=True)
            elif hasattr(chunk, "dict"):
                obj = chunk.dict(exclude_none=True)
            else:
                obj = dict(chunk)
            yield f"data: {json.dumps(obj)}\n\n"
        except Exception as e:
            logger.warning("Stream chunk serialize: %s", e)
    yield "data: [DONE]\n\n"


def _detect_openai_endpoint(body: dict, incoming_path: str) -> str:
    """Pick the right OpenAI endpoint based on request payload format."""
    if "input" in body and "messages" not in body:
        return "/responses"
    path = incoming_path
    if not path.startswith("/v1"):
        path = f"/v1{path}"
    return path.removeprefix("/v1")


async def _openai_passthrough(
    request: Request, body: dict
) -> StreamingResponse | JSONResponse:
    """Forward request to OpenAI API unchanged and relay the response."""
    if not _openai_client or not _openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="OpenAI passthrough not configured (OPENAI_API_KEY missing)",
        )

    model = body.get("model", "?")
    endpoint = _detect_openai_endpoint(body, request.url.path)
    logger.info("OpenAI passthrough → %s  endpoint=%s", model, endpoint)

    headers = {
        "Authorization": f"Bearer {_openai_api_key}",
        "Content-Type": "application/json",
    }
    for key in ("openai-organization", "openai-project"):
        val = request.headers.get(key)
        if val:
            headers[key] = val

    stream = body.get("stream", False)

    if stream:
        req = _openai_client.build_request("POST", endpoint, json=body, headers=headers)
        upstream = await _openai_client.send(req, stream=True)
        if upstream.status_code != 200:
            error_body = await upstream.aread()
            await upstream.aclose()
            return JSONResponse(
                status_code=upstream.status_code,
                content=json.loads(error_body)
                if error_body
                else {"error": "upstream error"},
            )

        async def relay():
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await upstream.aclose()

        resp_headers = {
            k: v
            for k, v in upstream.headers.items()
            if k.lower()
            not in ("transfer-encoding", "content-encoding", "content-length")
        }
        return StreamingResponse(
            relay(), media_type="text/event-stream", headers=resp_headers
        )

    resp = await _openai_client.post(endpoint, json=body, headers=headers)
    return JSONResponse(status_code=resp.status_code, content=resp.json())


@app.post("/v1/responses")
@app.post("/responses")
@app.post("/gateway/llm/v1/responses")
@app.post("/gateway/llm/responses")
async def responses_passthrough(request: Request, _: str = Depends(_verify_key)):
    """Handle OpenAI Responses API requests."""
    body = await request.json()
    model_name = body.get("model", "")
    if _is_openai_model(model_name):
        return await _openai_passthrough(request, body)
    raise HTTPException(
        status_code=400, detail=f"Responses API not supported for model: {model_name}"
    )


async def _llm_call(req: dict) -> str:
    """Make a single LLM call via the router and return the text content."""
    if _router is None:
        raise RuntimeError("Router not initialised")
    response = await _router.acompletion(**req)
    if hasattr(response, "choices") and response.choices:
        return response.choices[0].message.content or ""
    if isinstance(response, dict):
        choices = response.get("choices", [])
        return choices[0]["message"]["content"] if choices else ""
    return str(response)


async def _multi_call_prepare(
    all_messages: list[dict],
    history: list[dict],
    tail: list[dict],
    tools: list | None = None,
    system=None,
) -> tuple[str, str]:
    """Run condensation and generation in parallel via the condensation model."""
    condense_req = build_condensation_request(history)
    generate_req = build_generation_request(all_messages, tools=tools, system=system)

    logger.info(
        "Multi-call: launching condensation (%d history msgs) and generation (%d total msgs) in parallel via %s",
        len(history),
        len(all_messages),
        CONDENSATION_MODEL,
    )

    summary, draft = await asyncio.gather(
        _llm_call(condense_req),
        _llm_call(generate_req),
    )

    logger.info(
        "Multi-call complete: summary=%d chars, draft=%d chars",
        len(summary),
        len(draft),
    )
    return summary, draft


@app.post("/v1/chat/completions")
@app.post("/chat/completions")
@app.post("/gateway/llm/v1/chat/completions")
@app.post("/gateway/llm/chat/completions")
async def chat_completions(request: Request, _: str = Depends(_verify_key)):
    """Main chat completion endpoint."""
    body = await request.json()
    raw_model = body.get("model", "")
    stream = body.get("stream", False)
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    logger.info("Request: id=%s model=%s stream=%s", request_id, raw_model, stream)
    logger.info(
        "Request headers: %s",
        {k: v for k, v in request.headers.items() if k.lower() != "authorization"},
    )

    if _is_openai_model(raw_model):
        return await _openai_passthrough(request, body)

    if not raw_model:
        raw_model = next(iter(sorted(_model_names)), None)
    if not raw_model:
        raise HTTPException(status_code=400, detail="Missing model")

    model_name = _resolve_model_name(raw_model)
    if model_name != raw_model:
        logger.info("Resolved model name: %s → %s", raw_model, model_name)
    if model_name not in _model_names:
        raise HTTPException(status_code=400, detail=f"Unknown model: {raw_model}")
    if _router is None:
        raise HTTPException(status_code=503, detail="Router not initialised")

    data = process_request_body(dict(body), logger)

    extra = _variant_kwargs(raw_model)
    if extra:
        logger.info("Model variant %s → injecting %s", raw_model, list(extra.keys()))

    messages = data.get("messages", [])
    tools = data.get("tools")
    system = data.get("system")

    max_ctx = context_limit_for_model(model_name)
    split = split_for_condensation(
        messages, max_ctx, logger, tools=tools, system=system
    )
    if split is not None:
        history, tail = split
        try:
            summary, draft = await _multi_call_prepare(
                all_messages=messages,
                history=history,
                tail=tail,
                tools=tools,
                system=system,
            )
            messages = inject_draft_into_messages(draft, summary, tail, logger)
        except Exception as e:
            logger.exception("Multi-call failed, falling back to tail-only: %s", e)
            messages = tail

    max_tokens = data.get("max_tokens") or data.get("max_completion_tokens") or 16384
    temperature = data.get("temperature")

    thinking_cfg = extra.get("thinking", {})
    thinking_budget = thinking_cfg.get("budget_tokens", 0)
    thinking_enabled = thinking_cfg.get("type") in ("enabled", "adaptive")
    if thinking_budget:
        if max_tokens <= thinking_budget:
            max_tokens = thinking_budget + 4096
        temperature = 1.0
    elif thinking_enabled:
        # Adaptive thinking (e.g. Sonnet 5) — no budget_tokens but still needs
        # temperature = 1.0 as required by the Anthropic/Vertex thinking API.
        temperature = 1.0

    kwargs = {
        "model": model_name,
        "messages": messages,
        "stream": stream,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "tools": tools,
        **extra,
    }
    if system:
        kwargs["system"] = system

    try:
        response = await _router.acompletion(**kwargs)
    except Exception as e:
        logger.exception("LiteLLM Router acompletion error: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e

    if stream:
        return StreamingResponse(
            _stream_chunks(response),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    try:
        if hasattr(response, "model_dump"):
            return response.model_dump(exclude_none=True)
        if hasattr(response, "dict"):
            return response.dict(exclude_none=True)
        return dict(response)
    except Exception as e:
        logger.warning("Response serialize: %s", e)
        return response
