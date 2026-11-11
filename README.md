# ODAS

Case management for NGOs and jurists who work in *zaken* (cases): a zaak is a
folder on disk, readable without the app. Read [`ARCHITECTURE.md`](ARCHITECTURE.md)
for the system invariants, [`src/odas/builtin/handleiding.md`](src/odas/builtin/handleiding.md)
for the user-facing behaviour, and [`wip/backlog.md`](wip/backlog.md) for known
gaps. The data model is best read from a real example,
[`tests/data/veenwacht/`](tests/data/veenwacht/).

## What ODAS is for

ODAS supports case-centric work (*zaakgericht werken*). This is the method
Dutch civil-society groups use to track a request from intake to close.

### Who uses it

The tool serves small teams with small budgets:

- small NGOs that handle Woo requests (Dutch freedom-of-information
  requests) or complaints from citizens;
- journalist collectives that track sources, requests, and leads as cases;
- jurists and legal-aid workers who run objection procedures or advice
  requests.

These groups often have no technical staff. They need a tool that is cheap
to run and easy to learn. Many current users manage cases today by e-mail
and spreadsheets, or by a paid case-management product built for a bigger
budget.

### What it does

Each case (*zaak*) holds one record with:

- the case data: title, status, deadline, and reference number;
- a log of every contact with the submitter, in or out;
- the documents that belong to the case, with searchable text;
- a secure link so a submitter can follow their own case, with no account;
- an audit trail of who changed what, and when;
- for jurists, a lookup of law text linked to the case.

### Design goals

**Sovereignty.** An organisation runs ODAS on its own server. The
organisation keeps full control of its own data, at all times. No case
data has to pass through a third-party company.

**Simplicity.** A zaak is a folder of plain text files on disk. Any
standard tool can read the data. This keeps the data portable, and safe
from lock-in to one vendor. The app itself stays simple. Older users, and
users with low technical skill, can manage a case with it.


## Quick start

```bash
source init.sh         # 1. install uv and the dependencies
./start_dev.sh         # 2. serve on :8000, auth bypassed
```

`start_dev.sh` copies the example data from `tests/data/veenwacht` into
`/tmp/odas-dev`. Stichting Veenwacht does not exist: the organisation and its
zaken are invented. For a data dir of your own, run `odas init` in an empty
folder, then `odas config check`. It seeds only a dir that holds no `.app/`, so it never
overwrites real data. To start over, run `rm -rf /tmp/odas-dev`.

## Development

```bash
inv ci                           # lint + tests
inv check                        # validate a data dir's zaken
inv format                       # format code
uv run odas config check         # in a data dir, or set ODAS_DATA_DIR
```

`CLAUDE.md` has the TDD workflow this repo follows: a change starts with a test.
The app migrates its own data dir at start when the layout revision is behind.
`odas upgrade` shows that plan first. `scripts/README.md` covers the helpers that
stay outside the app.

## Ask Claude about a zaak

Point Claude at the data dir itself. Every zaak is a folder of markdown, every
document carries its own text beside it, and every tracked law is a file, so
`grep`, `find` and `cat` reach all of it. The volume carries the skill that
explains its own layout, in `.claude/skills/`.

```bash
cd "$ODAS_DATA_DIR"            # the data dir, or a copy of it
claude                         # opened on that folder
```

Make a real change in ODAS, never in a copy.

## Deploy

```bash
inv bump patch   # tag vX.Y.Z, then: git push origin vX.Y.Z
inv deploy       # build + push the org-agnostic image, then restart the services
```

`inv deploy` reads `ODAS_DEPLOY_REGISTRY`, `ODAS_DEPLOY_VPS` and
`ODAS_DEPLOY_STACK`; see [`.env.example`](.env.example). Compose services,
secrets and routing for each organisation live in your own deployment repo.
[`docker-compose.example.yml`](docker-compose.example.yml) shows the shape.

## Licence

ODAS is free software under the [GNU AGPL, version 3 or later](LICENSE). If you
run a changed version for other people, you must offer them its source.
Report a vulnerability as [`SECURITY.md`](SECURITY.md) describes.
