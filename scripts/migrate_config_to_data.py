#!/usr/bin/env python3
"""Give a data dir its own schema: layout 3 -> 4.

Before layout 4 the schema lived in the image, in `src/odas/builtin/*.yaml`, and
`ODAS_ORG` picked which profile to merge. From layout 4 on, the data dir owns a
complete `.app/config.yaml` and nothing merges onto it.

Layout 4 also moved the environment into the data dir. The config file carries
`oidc:`, `smtp:` and `server:`, and the three credentials move to a `secrets.yaml`
beside it. So this script:

  1. copies the organisation's config file in,
  2. writes `secrets.yaml` (0600) from the credentials in the environment,
  3. drops the `app-version` stamp that `version:` inside the config replaces.

Get the config from the repo -- `tests/data/<org>/.app/config.yaml` holds the one
each deployment ran on -- edit its `oidc:` block for the real issuer, and scp it
to the VPS beside this script. Run it with the old compose environment exported,
so step 2 finds the credentials:

    set -a; . /srv/odas.env; set +a
    python3 migrate_config_to_data.py /data --from my-config.yaml
    python3 migrate_config_to_data.py /data --from my-config.yaml --apply

After it reports zero actions, strip every env var except TZ and ODAS_DATA_DIR
from the compose service and deploy the image.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

TARGET_VERSION = 4
SOURCE_VERSION = "3"  # major recorded in the .app/app-version this replaces
SECRETS_MODE = 0o600

# The env var each credential came from, before layout 4.
SECRETS_FROM_ENV = {
    "oidc_client_secret": "OIDC_CLIENT_SECRET",
    "pocket_id_api_key": "POCKET_ID_API_KEY",
    "smtp_pass": "SMTP_PASS",
}

# TODO(deploy): deployment is deferred, so this has never run against a real
# volume. Before the first run: snapshot, dry-run, and read every line of the
# output. Then delete this guard and the --i-have-a-snapshot flag with it.
DEFERRED = (
    "Deployment is deferred and this script has not been run against a real volume yet.\n"
    "Take a volume snapshot first, then re-run with --i-have-a-snapshot."
)


def _has_version(text: str) -> bool:
    """A top-level `version:` key, without pulling in a YAML dependency."""
    return any(line.startswith("version:") for line in text.splitlines())


def migrate(data_dir: Path, source: Path, dry_run: bool = True, force: bool = False) -> int:
    """Install the schema and drop the old stamp. Returns the number of actions."""
    prefix = "  [dry] " if dry_run else "  "
    actions = 0

    if not source.is_file():
        sys.exit(f"--from {source} does not exist.")
    text = source.read_text(encoding="utf8")
    if not _has_version(text):
        sys.exit(f"{source} has no top-level `version:` key; it is not a layout-4 config.")

    app_dir = data_dir / ".app"
    target = app_dir / "config.yaml"
    stamp = app_dir / "app-version"

    # Refuse a volume that is not where this migration starts: a pre-3 layout needs
    # its own migration first, and a missing stamp means the dir is not layout 3.
    if stamp.is_file():
        found = stamp.read_text(encoding="utf8").strip()
        if found.split(".")[0] != SOURCE_VERSION:
            sys.exit(f"{stamp} says {found!r}; this script migrates layout {SOURCE_VERSION} only.")
    elif not target.is_file():
        sys.exit(f"{data_dir} has neither {stamp.name} nor {target.name}; it is not a data dir.")

    if target.is_file() and not force:
        # The schema is what every zaak is read through, so replacing one that is
        # already there is never routine: make the operator say so.
        print("  SKIP config.yaml: already exists (pass --force to replace)")
    else:
        print(f"{prefix}write {target}")
        if not dry_run:
            app_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        actions += 1

    secrets = app_dir / "secrets.yaml"
    if secrets.is_file():
        # A credential lost to a rerun takes the deployment down: never replace one.
        print("  SKIP secrets.yaml: already exists")
    else:
        values = {k: os.environ.get(v, "") for k, v in SECRETS_FROM_ENV.items()}
        for key, env_var in SECRETS_FROM_ENV.items():
            if not values[key]:
                print(f"  NOTE {env_var} is not set; {key} will be empty in {secrets.name}")
        print(f"{prefix}write {secrets} (mode 0600, {sum(map(bool, values.values()))} set)")
        if not dry_run:
            app_dir.mkdir(parents=True, exist_ok=True)
            # json.dumps quotes and escapes; a double-quoted JSON string is valid YAML.
            body = "".join(f"{k}: {json.dumps(v)}\n" for k, v in values.items())
            secrets.write_text(f"# Credentials for this data dir. Keep mode 0600.\n{body}")
            os.chmod(secrets, SECRETS_MODE)
        actions += 1

    if stamp.is_file():
        print(f"{prefix}remove {stamp} (replaced by `version:` in config.yaml)")
        if not dry_run:
            stamp.unlink()
        actions += 1

    return actions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", nargs="?", default="data", type=Path)
    parser.add_argument("--from", dest="source", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="Write; default is a dry run.")
    parser.add_argument("--force", action="store_true", help="Replace an existing config.yaml.")
    parser.add_argument(
        "--i-have-a-snapshot", action="store_true", help="Confirm the volume is backed up."
    )
    args = parser.parse_args()

    if not args.data_dir.is_dir():
        sys.exit(f"{args.data_dir} is not a directory.")
    if args.apply and not args.i_have_a_snapshot:
        sys.exit(DEFERRED)

    print(f"{'Applying' if args.apply else 'Dry run'}: {args.data_dir} -> layout {TARGET_VERSION}")
    actions = migrate(args.data_dir, args.source, dry_run=not args.apply, force=args.force)
    print(f"{actions} action(s).")


if __name__ == "__main__":
    main()
