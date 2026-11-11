# paperus server: API, website and background worker in one image.
#   docker run … paperus-server          migrate, then serve on port 8000
#   docker run … paperus-server worker   background jobs

# uv, from its own image (a FROM line, so Dependabot keeps it current).
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM node:26-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# The dependencies' files with the project's own version as 0: each release
# changes only that, and the dependencies' layer stays the same layer, which
# an update then need not download again.
FROM python:3.13-slim AS dependencies
COPY server/pyproject.toml server/uv.lock /lock/
RUN python3 - <<'PY'
import re
from pathlib import Path
project = Path("/lock/pyproject.toml")
text = project.read_text()
name = re.search(r'^name = "([^"]+)"', text, re.M).group(1)
project.write_text(re.sub(r'^version = "[^"]*"', 'version = "0"', text, count=1, flags=re.M))
lock = Path("/lock/uv.lock")
pattern = r'(name = "%s"\nversion = )"[^"]*"' % re.escape(name)
lock.write_text(re.sub(pattern, r'\1"0"', lock.read_text()))
PY

FROM python:3.13-slim
LABEL org.opencontainers.image.source="https://github.com/qcode-uni-a/paperus" \
      org.opencontainers.image.description="paperus server: API, website and worker" \
      org.opencontainers.image.licenses="Apache-2.0"

COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    PAPERUS_WEB_PATH=/app/web \
    PAPERUS_STORAGE_PATH=/data/files \
    PAPERUS_BACKUP_PATH=/data/backups \
    PAPERUS_COPY_PATH=/data/copy

WORKDIR /app
COPY --from=dependencies /lock/pyproject.toml /lock/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY server/pyproject.toml server/uv.lock server/README.md ./
COPY server/src ./src
RUN uv sync --frozen --no-dev
COPY --from=web /web/build ./web
COPY docker/start.sh /usr/local/bin/paperus-start

RUN groupadd --system --gid 1000 paperus \
    && useradd --system --uid 1000 --gid paperus --create-home --home-dir /home/paperus paperus \
    && mkdir -p /data/files /data/backups /data/copy && chown -R paperus:paperus /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"]
ENTRYPOINT ["paperus-start"]
CMD ["serve"]
