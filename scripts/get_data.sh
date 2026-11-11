#!/bin/bash
set -euo pipefail

# Puts one organisation's real data in $ODAS_DATA_DIR, so development can run
# against real content instead of the example data. Configure it in .env.
#
# DEV_REMOTE is an rsync source: the live volume on the VPS. What lands here is
# a copy, never a working copy. Rerun to refresh, and do not edit it: a rerun
# deletes whatever the remote does not have. The live volume is the only
# original, and restic backs it up every night.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

: "${ODAS_DATA_DIR:?not set. Copy .env.example to .env and set it.}"
: "${DEV_REMOTE:?not set. Copy .env.example to .env and set it.}"

echo "Copying $DEV_REMOTE into $ODAS_DATA_DIR..."
mkdir -p "$ODAS_DATA_DIR"
# Trailing slash on the source: copy the *contents* of the remote dir, not the
# dir itself (which would nest it one level deeper). --inplace because some
# attachment names are long enough that rsync's temporary name does not fit.
rsync -avz --inplace --delete --progress --stats "$DEV_REMOTE/" "$ODAS_DATA_DIR/"

# No migrations here. A volume that falls behind is migrated in place on the VPS:
# a migration on the copy would only hide the gap. See scripts/README.md.

# Report problems in the data, but do not fail: real data can hold them, and
# the copy is still usable.
uv run odas check || echo "Note: 'odas check' found problems in the real data."

echo
echo "Done. Start the dev server with ./start_dev.sh"
