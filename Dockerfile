FROM ghcr.io/astral-sh/uv:0.13.1 AS uv
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
# Use the image's CPython only; never fetch a managed interpreter during the build.
ENV UV_PYTHON_DOWNLOADS=never UV_PYTHON=/usr/local/bin/python3.12 UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 demo
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY scripts ./scripts
COPY evals ./evals
COPY fixtures/synthetic ./fixtures/synthetic
COPY migrations ./migrations
COPY alembic.ini ./
COPY frontend ./frontend
RUN uv sync --frozen --no-dev && mkdir -p /home/demo/.cache/huggingface \
    && chown -R demo:demo /home/demo
ENV PATH="/app/.venv/bin:$PATH" HF_HOME=/home/demo/.cache/huggingface
# Fail the build, not the demo, if the decoder or a speech dependency is missing.
RUN ffmpeg -hide_banner -version >/dev/null \
    && python -c "import ctranslate2, faster_whisper, parselmouth, soundfile, webrtcvad; \
import patient_memory.api, scripts.hosted_demo"
USER demo
CMD ["python", "-m", "scripts.hosted_demo", "serve"]
