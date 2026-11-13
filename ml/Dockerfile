# paperus-ml. It comes with the recommended models for its device (in
# /models); others are downloaded to /cache on first use: mount a volume
# there so they survive updates.
#
# DEVICE=cpu (the default) builds the CPU image; DEVICE=cuda the "-cuda"
# image for NVIDIA GPUs: the same, with ONNX Runtime's GPU build and CUDA and
# cuDNN from NVIDIA's Python packages (about 2.5 GB more). It uses the GPU
# when the container gets one (see docs/operations.md), else the CPU.

# uv, from its own image (a FROM line, so Dependabot keeps it current).
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

# The dependencies' files with the project's own version as 0: each release
# changes only that, and the dependencies' layer stays the same layer, which
# an update then need not download again.
FROM python:3.13-slim AS dependencies
COPY pyproject.toml uv.lock /lock/
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

FROM python:3.13-slim AS base
COPY --from=uv /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    PAPERUS_ML_CACHE_PATH=/cache \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app
COPY --from=dependencies /lock/pyproject.toml /lock/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# The recommended models for the device (models.py), downloaded with only
# the two files that say which: a release that changes neither keeps this
# layer, and the files' times are fixed so a new download is the same layer.
FROM base AS models
ARG DEVICE=cpu
COPY src/paperus_ml/models.py src/paperus_ml/download.py /build/paperus_ml/
RUN touch /build/paperus_ml/__init__.py \
    && PYTHONPATH=/build /app/.venv/bin/python -m paperus_ml.download --device "$DEVICE" /models \
    && find /models -exec touch --no-dereference --date=@0 {} +

FROM base
ARG DEVICE=cpu
LABEL org.opencontainers.image.source="https://github.com/qcode-uni-a/paperus" \
      org.opencontainers.image.description="paperus machine learning service (embeddings; ${DEVICE})" \
      org.opencontainers.image.licenses="Apache-2.0"
# The GPU build of the same ONNX Runtime version as in uv.lock (before the
# code: a change to it leaves this layer alone too).
RUN if [ "$DEVICE" = cuda ]; then \
        version="$(uv pip show onnxruntime | sed -n 's/^Version: //p')" \
        && uv pip uninstall onnxruntime \
        && uv pip install "onnxruntime-gpu[cuda,cudnn]==$version"; \
    elif [ "$DEVICE" != cpu ]; then echo "DEVICE must be cpu or cuda" >&2; exit 1; fi
COPY --from=models /models /models
ENV PAPERUS_ML_BUILTIN_PATH=/models
# Then the project itself, with its real version; ONNX Runtime left as it is
# (the CPU build, or the GPU one in its place).
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --inexact --no-install-package onnxruntime
# For the NVIDIA Container Toolkit: which GPU features the container needs.
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility

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
