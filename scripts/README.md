# scripts/

The app migrates its own data dir at start: `src/odas/migrations/`. It backs up
every file a step can touch to `.backups/<timestamp>/`, and runs the steps in
order up to `DATA_VERSION`. `odas upgrade` shows the plan; `odas upgrade --apply`
writes.

The scripts here cover a data dir older than layout 4. The app cannot migrate
such a dir, because a step needs credentials or a decision.

| script | what it does |
|---|---|
| `migrate_to_types.py` | layout 2 → 3: stamp `soort:`/`titel:`, fold `dossiers/*` into `zaken/`, letter-order log entries, stamp `.app/app-version` |
| `migrate_log_entries.py` | helper of `migrate_to_types.py`: log-entry ordering letter and legacy field names |
| `migrate_config_to_data.py` | layout 3 → 4: install `.app/config.yaml` and `.app/secrets.yaml`, drop the `app-version` stamp |
| `get_data.sh` | copy a live volume to `$ODAS_DATA_DIR` with rsync, then check it. The copy is disposable: the next run deletes local changes |
| `sync_users_to_pocketid.py` | push the local user list to the Pocket-ID IdP |

## Layout 3 → 4 needs a hand

`migrate_config_to_data.py` installs the config of the organisation. It reads
three credentials (`OIDC_CLIENT_SECRET`, `POCKET_ID_API_KEY`, `SMTP_PASS`) from
the environment and writes them to `.app/secrets.yaml`, mode 0600.

```bash
python3 scripts/migrate_config_to_data.py /data --from my-config.yaml          # shows the plan
python3 scripts/migrate_config_to_data.py /data --from my-config.yaml --apply  # writes
```

From layout 4 the app reads only `ODAS_DATA_DIR` and `ODAS_TEST_MODE`. Remove
all other variables from the compose service.
