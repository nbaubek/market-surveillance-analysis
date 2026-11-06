FROM python:3.13-slim

WORKDIR /app

# uv binary, pinned to the version this project's lockfile is generated
# with (0.6.4 locally) so container and dev installs resolve identically.
COPY --from=ghcr.io/astral-sh/uv:0.6.4 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Dependencies first for layer caching; uv.lock makes the build
# reproducible (--frozen refuses a stale lock).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app.py ./
COPY data ./data

# Hugging Face Spaces serves from port 7860.
ENV PORT=7860
EXPOSE 7860
CMD [".venv/bin/python", "app.py"]
