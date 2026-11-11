# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# ODAS

FastAPI NGO case management. A `zaak` is a folder on disk.
Model: `README.md`. Invariants: `ARCHITECTURE.md`. Dutch manual (served by the app): `src/odas/builtin/handleiding.md`. Open work: `wip/backlog.md`.

## Commands (Python 3.12+, `uv`)

- `./start_dev.sh` — dev server on a copy at `/tmp/odas-dev` (`rm -rf /tmp/odas-dev` re-seeds).
- `inv lint` / `inv test` / `inv ci` — ruff+mypy / pytest+`node --test` / both.
- `uv run pytest tests/test_log.py -k name` — one test.
- `inv format` / `inv check` — format code / validate zaken.
- `inv bump <part>` then `inv deploy` — release.

## Invariants

- **No special orgs:** `.app/config.yaml` in the data dir defines all behavior. Nothing merges onto it.
- **One env var:** `ODAS_DATA_DIR` (default: current dir), plus `ODAS_TEST_MODE` (dev auth bypass). Credentials live only in `.app/secrets.yaml`.
- **Everything is a zaak:** one store (`$ODAS_DATA_DIR/zaken/`), one URL space. `soort` = YAML type. A dossier is `soort: dossier`.
- **Versioned data dir:** a layout change bumps `dataversion.DATA_VERSION` and adds a step to `migrations.STEPS`. Startup migrates old data dirs and refuses newer ones.
- **Docs are written, never generated.** A code-vs-doc gap goes in `wip/backlog.md`.

## Language

A name on disk stays Dutch. Other code names are English. Text a person reads is Dutch.
Example: `/zaken/{ref}/log/{name}/edit`. Form inputs keep their disk key (`titel`, `soort`).
Exception: `/inzien-{token}` is mailed to indieners. Never change it.

Disk terms (do not translate): `zaak`/`zaken`, `soort`, `dossier`, `indiener` (token access, no account), `behandelaar` (informative; access is via `experts`), `termijn`.

## Tests

- Example data dirs: `tests/data/{veenwacht,vms}/`. Fixtures: `tests/conftest.py`.
- Sentence-style names. No `unittest.mock`; use `monkeypatch` with small fakes.
- Build test data with writers (`zaak_create`, `index_write`, `log_write`), not hand-written frontmatter.
