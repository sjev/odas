#!/bin/bash
set -euo pipefail

# Two-way sync of this data dir with the server, by rsync. Git lives only on
# the server: odas-commit.sh (stek repo) commits there, so nothing merges.
#
# A file changed here since the last sync goes up. Then the server copy comes
# down, deletions too. A file changed on both sides stops the run. Delete
# files on the server: a file deleted here comes back. What the pull replaces
# or deletes here goes to .sync-trash/ first, for 30 days.
#
# Usage: ./sync.sh [-n | --init | --mine]
#   -n      show what would move; the server still commits
#   --init  first sync on this machine: the server copy wins
#   --mine  a file changed on both sides: this copy wins

cd "$(dirname "${BASH_SOURCE[0]}")"
source ./sync_config.sh

MODE=${1:-}
COMMIT=$REMOTE_STACK/server-scripts/odas-commit.sh
REF=refs/sync/$(hostname)
STAMP=.sync-stamp
TRASH=.sync-trash
# Server-only state and local tool output.
EXCLUDES=(--exclude=/.git/ --exclude="/$STAMP*" --exclude="/$TRASH/"
          --exclude=/.backups/ --exclude=/.claude/
          --exclude=.migrating --exclude=/.app/secrets.yaml
          --exclude=/.app/.secret_key --exclude=/.app/mail.key
          --exclude=/.app/mail.crt --exclude=/.app/backups/
          --exclude=/.app/app-data/ --exclude=/.app/logs/ --exclude=out/
          --exclude=__pycache__/ --exclude='*.aux')
# Only the server writes these: the pull brings them down, the push never sends them.
PUSH_EXCLUDES=(--exclude=audit.log --exclude=.access-token)
DRY=()
[ "$MODE" = -n ] && DRY=(-n)

remote() { ssh -n "$REMOTE_HOST" "$@"; }

pull() {  # $1: a file of rsync patterns to keep here as they are; then rsync options
    local keep=$1
    shift
    rsync -aO --delete "$@" "${DRY[@]}" --out-format='  %o %n' "${EXCLUDES[@]}" \
        --exclude-from="$keep" --backup --backup-dir="$PWD/$TRASH/$(date +%F-%H%M%S)" \
        "$REMOTE_HOST:$REMOTE_DIR/" ./
}

check_remote_volume
# Made now, moved in place at the end: an edit during the run counts next time.
touch "$STAMP.new"

if [ "$MODE" = --init ]; then
    [ ! -e "$STAMP" ] || { echo "This machine syncs already. Run ./sync.sh."; exit 1; }
    # Compare content: a fresh copy here differs from the server only in mtimes.
    pull /dev/null --checksum
    remote "$COMMIT $REMOTE_DIR 'sync: $(hostname) init' $REF"
    mv "$STAMP.new" "$STAMP"
    exit 0
fi

[ -e "$STAMP" ] || { echo "First sync on this machine. Run ./sync.sh --init."; exit 1; }
check_local_volume

ours=$(mktemp)
theirs=$(mktemp)
keep=$(mktemp)
trap 'rm -f "$ours" "$theirs" "$keep"' EXIT

find . \( -path ./.git -o -path "./$TRASH" \) -prune -o -type f -newer "$STAMP" -print \
    | sed 's|^\./||' | sort > "$ours"
remote "$COMMIT $REMOTE_DIR && git -C $REMOTE_DIR -c core.quotepath=off \
    diff --no-renames --name-only $REF HEAD" | sort > "$theirs"
# Anchored and escaped, so the pull skips exactly these paths.
sed 's/[][*?\\]/\\&/g; s|^|/|' "$ours" > "$keep"

clashes=$(comm -12 "$ours" "$theirs")
if [ -n "$clashes" ] && [ "$MODE" != --mine ]; then
    echo "Changed here and on the server since the last sync:"
    sed 's/^/  /' <<<"$clashes"
    echo "Server copy: ssh $REMOTE_HOST git -C $REMOTE_DIR show HEAD:<file>"
    echo "Keep the server copy: delete the file here, then ./sync.sh."
    echo "Keep this copy (merge by hand first if needed): ./sync.sh --mine"
    exit 1
fi

echo "Up:"
rsync -aO "${DRY[@]}" --out-format='  %o %n' "${EXCLUDES[@]}" "${PUSH_EXCLUDES[@]}" \
    --files-from="$ours" ./ "$REMOTE_HOST:$REMOTE_DIR/"
echo "Down:"
pull "$keep"
[ "$MODE" != -n ] || { rm "$STAMP.new"; exit 0; }

remote "$COMMIT $REMOTE_DIR 'sync: $(hostname)' $REF"
mv "$STAMP.new" "$STAMP"
[ ! -d "$TRASH" ] || find "$TRASH" -mindepth 1 -maxdepth 1 -mtime +30 -exec rm -rf {} +
