# paperus-ml. Models are downloaded to /cache on first use; mount a volume
# there so they survive updates.
#
# DEVICE=cpu (the default) builds the CPU image; DEVICE=cuda the "-cuda"
# image for NVIDIA GPUs: the same, with ONNX Runtime's GPU build and CUDA and
# cuDNN from NVIDIA's Python packages (about 2.5 GB more). It uses the GPU
# when the container gets one (see docs/operations.md), else the CPU.

# uv, from its own image (a FROM line, so Dependabot keeps it current).
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM python:3.13-slim
ARG DEVICE=cpu
LABEL org.opencontainers.image.source="https://github.com/qcode-uni-a/paperus" \
      org.opencontainers.image.description="paperus machine learning service (embeddings; ${DEVICE})" \
      org.opencontainers.image.licenses="Apache-2.0"

COPY --from=uv /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    PAPERUS_ML_CACHE_PATH=/cache \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
# The GPU build of the same ONNX Runtime version as in uv.lock.
RUN if [ "$DEVICE" = cuda ]; then \
        version="$(uv pip show onnxruntime | sed -n 's/^Version: //p')" \
        && uv pip uninstall onnxruntime \
        && uv pip install "onnxruntime-gpu[cuda,cudnn]==$version"; \
    elif [ "$DEVICE" != cpu ]; then echo "DEVICE must be cpu or cuda" >&2; exit 1; fi
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
