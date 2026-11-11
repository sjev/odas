# ODAS

ODAS is a sovereign, plain-file case management system. It is for
public-interest NGOs, jurists, and legal-aid workers. Their case files must
stay under their own control.

Each case (*zaak*) is a folder of Markdown files with YAML frontmatter, beside
the raw documents (`.pdf`, `.eml`). There is no database of record. If you
remove the application, `ls`, `grep` and a text editor still read every case.

## Why ODAS

Most case-management tools are SaaS products, or heavy municipal platforms
such as VNG ZGW / OpenZaak. Both are a bad fit for a small team with no
technical staff:

| Need | ODAS answer |
|---|---|
| Sovereignty | One organisation runs one instance on its own server. No case data goes through a third party. |
| No lock-in | The data is plain files in a documented layout. Any standard tool reads it. |
| Low cost | One container, no database, no queue, no client build step. |
| Easy to learn | Server-rendered pages. Status and deadline fields are the workflow. |

## What a zaak holds

- case data: title, status, deadline, reference number;
- a log of each contact with the submitter, in or out, with e-mail capture;
- documents with their extracted text, so you can search them;
- a token link, so a submitter (*indiener*) can follow the case with no account;
- an append-only audit trail of who changed what, and when;
- for jurists, links to the law text that applies.

Read a real example: [`tests/data/veenwacht/`](tests/data/veenwacht/).
Stichting Veenwacht and its zaken are invented.

## Quick start

```bash
source init.sh     # install uv and the dependencies
./start_dev.sh     # serve on :8000 with auth bypassed
```

`start_dev.sh` copies the example data into `/tmp/odas-dev`. To start over,
run `rm -rf /tmp/odas-dev`. `./start_demo.sh` serves the public demo on :8001.

For a data dir of your own, run `odas init` in an empty folder. Then run
`odas config check`. `odas init` never writes into a dir that has `.app/`.

## Documentation

| File | Content |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | System shape and invariants |
| [`src/odas/builtin/handleiding.md`](src/odas/builtin/handleiding.md) | User manual (Dutch), served by the app |
| [`wip/backlog.md`](wip/backlog.md) | Known gaps and open work |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How to contribute |
| [`scripts/README.md`](scripts/README.md) | Helpers outside the app |

## Development

```bash
inv ci                     # lint + tests
inv check                  # validate the zaken in a data dir
inv format                 # format code
uv run odas config check   # in a data dir, or set ODAS_DATA_DIR
```

Each change starts with a test; see [`CLAUDE.md`](CLAUDE.md). At start, the
app migrates a data dir with an old layout. `odas upgrade` shows the plan first.

## Deploy

```bash
inv bump patch   # tag and push vX.Y.Z; GitHub builds ghcr.io/sjev/odas
inv deploy       # wait for that build, then restart the services
```

`inv deploy` reads `ODAS_DEPLOY_VPS` and `ODAS_DEPLOY_STACK` (see
[`.env.example`](.env.example)). Keep the services,
secrets and routing of each organisation in your own deployment repo.
[`docker-compose.example.yml`](docker-compose.example.yml) shows the shape.

## Licence

ODAS is free software under the [GNU AGPL, version 3 or later](LICENSE). If you
run a changed version for other people, you must offer them its source.
To report a vulnerability, follow [`SECURITY.md`](SECURITY.md).
