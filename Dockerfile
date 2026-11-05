# paperus server: API, website and background worker in one image.
#   docker run … paperus-server          migrate, then serve on port 8000
#   docker run … paperus-server worker   background jobs

FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.13-slim
LABEL org.opencontainers.image.source="https://github.com/qcode-uni-a/paperus" \
      org.opencontainers.image.description="paperus server: API, website and worker" \
      org.opencontainers.image.licenses="Apache-2.0"

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    PAPERUS_WEB_PATH=/app/web \
    PAPERUS_STORAGE_PATH=/data/files

WORKDIR /app
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY server/README.md ./
COPY server/src ./src
RUN uv sync --frozen --no-dev
COPY --from=web /web/build ./web
COPY docker/start.sh /usr/local/bin/paperus-start

RUN groupadd --system --gid 1000 paperus \
    && useradd --system --uid 1000 --gid paperus --create-home --home-dir /home/paperus paperus \
    && mkdir -p /data/files && chown -R paperus:paperus /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"]
ENTRYPOINT ["paperus-start"]
CMD ["serve"]
