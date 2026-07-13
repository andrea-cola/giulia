# giulia_gateway — runs on Cloud Run.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1

COPY pyproject.toml README.md ./
COPY giulia_gateway/ giulia_gateway/

RUN uv pip install --system .

EXPOSE 8080

CMD ["uvicorn", "giulia_gateway.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
