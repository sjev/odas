#!/bin/bash
set -euo pipefail

# Run the public demonstration locally, the way the VPS runs it.
#
# The data dir is NOT read from the environment. A shell that already exports
# ODAS_DATA_DIR points at a real organisation, and `odas demo init` would write
# the demo's schema over that organisation's own. Pass a path as the first
# argument to use another one.
#
# ODAS_TEST_MODE is cleared as well: the demo declares itself in
# `.app/config.yaml`, and the dev bypass would also open the JSON write route.
#
# Port 8001, so this runs beside ./start_dev.sh and the two can be compared.
# To start over: rm -rf /tmp/odas-demo

export ODAS_DATA_DIR="${1:-/tmp/odas-demo}"
unset ODAS_TEST_MODE

config="$ODAS_DATA_DIR/.app/config.yaml"
if [ ! -f "$config" ]; then
    echo "Seeding $ODAS_DATA_DIR from the demo seed in the package."
    uv run odas demo init
elif ! grep -q '^demo:' "$config"; then
    # Whatever lies here belongs to somebody. Never seed over it, never serve it
    # as a demo: without a `demo:` section this is a real organisation's volume.
    echo "Refusing: $config declares no 'demo:' section, so this is not a demo." >&2
    echo "Use a fresh path, for example: ./start_demo.sh /tmp/odas-demo" >&2
    exit 1
fi

echo "Demo at http://localhost:8001 -- nobody signs in, everyone shares the zaken."
echo "Reset it with: ODAS_DATA_DIR=$ODAS_DATA_DIR uv run odas demo reset"
uv run fastapi dev --port 8001 src/odas/app.py
