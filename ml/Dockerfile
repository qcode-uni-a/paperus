# paperus-ml: CPU image. Models are downloaded to /cache on first use;
# mount a volume there so they survive updates (like Immich's model-cache).
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PAPERUS_ML_CACHE_PATH=/cache \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

RUN useradd --system --uid 1000 paperus && mkdir /cache && chown paperus /cache
USER paperus
VOLUME /cache
EXPOSE 3003

HEALTHCHECK --interval=30s --timeout=5s \
    CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3003/ping')"]
CMD ["/app/.venv/bin/paperus-ml", "--host", "0.0.0.0", "--port", "3003"]
