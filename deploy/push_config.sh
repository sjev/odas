#!/bin/bash
set -euo pipefail

# Checks the config of this data dir, syncs it, then restarts the services.
# The app reads its config only at start, so a sync alone changes nothing.
# Git on the server holds every earlier config.
#
# It stops when:
#   - `version:` differs from the server (a layout change needs `inv deploy`),
#   - the config does not load, or a zaak does not fit it,
#   - sync.sh stops.

cd "$(dirname "${BASH_SOURCE[0]}")"
source ./sync_config.sh

check_local_volume
check_remote_volume

version() { grep -m1 '^version:' | awk '{print $2}'; }
local_v=$(version < .app/config.yaml)
remote_v=$(ssh -n "$REMOTE_HOST" cat "$REMOTE_DIR/.app/config.yaml" | version)
[ "$local_v" = "$remote_v" ] \
    || { echo "version: $local_v here, $remote_v there. Use inv deploy. Stopping."; exit 1; }

# The repo code, not the installed tool: `odas check` migrates a data dir that
# is behind, and this copy must stay what the server has.
ODAS_DATA_DIR=$PWD uv run --quiet --project "$ODAS_REPO" python -c '
from odas import appconfig, zaak
appconfig.get_config()
problems = zaak.check_all()
for p in problems:
    print(f"{p.path}: {p.message}")
raise SystemExit(bool(problems))
' || { echo "The config does not fit the data. Stopping."; exit 1; }

./sync.sh

read -r -p "Restart $SERVICES, so the config goes live? [y/N] " reply
[ "$reply" = "y" ] || { echo "Synced. Nothing was restarted."; exit 0; }
ssh -n "$REMOTE_HOST" "cd $REMOTE_STACK && docker compose restart $SERVICES"

echo
echo "Earlier versions: ssh $REMOTE_HOST git -C $REMOTE_DIR log -- .app/config.yaml"
