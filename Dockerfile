FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
# git lets hatch-vcs resolve the version from the tag in the copied .git.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN uv build --wheel \
    && uv export --no-dev --frozen --no-emit-project --no-hashes -o requirements.txt

FROM python:3.12-slim AS runtime
LABEL org.opencontainers.image.source="https://github.com/sjev/odas"
LABEL org.opencontainers.image.licenses="AGPL-3.0-or-later"
ENV PYTHONUNBUFFERED=1
WORKDIR /app
# Deps first — cached unless requirements.txt content changes.
COPY --from=builder /app/requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
# App wheel last — changes every build, but has no deps to download.
COPY --from=builder /app/dist/*.whl ./
RUN pip install --no-cache-dir --no-deps *.whl \
    && rm -f *.whl requirements.txt \
    && python -c "import odas"
USER 1000:1000
# The subcommand is the argument, so one image serves both containers:
# `serve` by default, `command: mailin` for the mail capture daemon.
ENTRYPOINT ["python", "-m", "odas"]
CMD ["serve"]
