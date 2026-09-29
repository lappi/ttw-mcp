# Образ для serverless-контейнера: сервер по Streamable HTTP на $PORT.
# uv нужен только для сборки окружения и в итоговый образ не попадает.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY ttw_mcp ./ttw_mcp
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
CMD ["ttw-mcp-http"]
