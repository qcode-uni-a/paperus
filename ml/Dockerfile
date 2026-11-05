# paperus-ml: CPU image. Models are downloaded to /cache on first use;
# mount a volume there so they survive updates.

# uv, from its own image (a FROM line, so Dependabot keeps it current).
FROM ghcr.io/astral-sh/uv:0.13.5 AS uv

FROM python:3.13-slim
LABEL org.opencontainers.image.source="https://github.com/qcode-uni-a/paperus" \
      org.opencontainers.image.description="paperus machine learning service (embeddings)" \
      org.opencontainers.image.licenses="Apache-2.0"

COPY --from=uv /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PAPERUS_ML_CACHE_PATH=/cache \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

RUN groupadd --system --gid 1000 paperus \
    && useradd --system --uid 1000 --gid paperus --create-home --home-dir /home/paperus paperus \
    && mkdir /cache && chown paperus:paperus /cache
COPY start.sh /usr/local/bin/paperus-ml-start
VOLUME /cache
EXPOSE 3003

HEALTHCHECK --interval=30s --timeout=5s \
    CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3003/ping')"]
ENTRYPOINT ["paperus-ml-start"]
CMD ["/app/.venv/bin/paperus-ml", "--host", "0.0.0.0", "--port", "3003"]
