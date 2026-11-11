#!/bin/bash
set -euo pipefail

# Load config from .env if present. Optional: the default below is enough.
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

export ODAS_DATA_DIR="${ODAS_DATA_DIR:-/tmp/odas-dev}"

# Local-dev auth bypass — never set this in production.
export ODAS_TEST_MODE=1

# Dev runs outside the repo, never against tests/data/ itself: clicking around
# creates and edits zaken, and those must not show up in git. A dir without
# .app/ is not a data dir, so seed it. A dir that holds .app/ stays as it is.
# To start over: rm -rf /tmp/odas-dev
if [ ! -d "$ODAS_DATA_DIR/.app" ]; then
    echo "Seeding $ODAS_DATA_DIR from tests/data/veenwacht."
    mkdir -p "$ODAS_DATA_DIR"
    cp -r tests/data/veenwacht/. "$ODAS_DATA_DIR/"
fi

uv run fastapi dev --port 8000 src/odas/app.py
