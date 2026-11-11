# Backlog

One line, one task: what to change, and where.

## Hand-off

- **Point `README.md` and `ARCHITECTURE.md` at the spec repo**
  (`odas-data-spec`, CC0). Replace "the data model is best read from a real
  example" with the link. The spec also answers the config key reference below.
- **Write the runbook**: build, deploy, restore, where the config lives. One page
  in the repo. Neither `ARCHITECTURE.md` nor `scripts/README.md` answers "the
  server is gone".
- **Write the `.app/config.yaml` key reference.** Generate it from the field
  types, or check it against them.
- **Run `inv backup.verify` and record the result.** Nobody has watched a data
  dir come back.

## Correctness

- **`odas wetten add` reads 0 articles of the Burgerlijk Wetboek.** BWBR0003045,
  BWBR0005288 and BWBR0005289 (boek 2, 5, 6) and the Omgevingsregeling
  (BWBR0045528) all come back empty; the Awb's
  `8:14` parses. Find what the BW XML nests differently in `wetten.py`.
- **Stop writing an undeclared `status:` on a type that declares none.**
  `zaak_create.create_minimal` passes `status=""` into `initial_fm`, so a new
  dossier gets a key its own schema calls unknown.
- **Rewrite the log frontmatter in `tests/data/`.** The corpora still carry
  `bcc` and `verzonden`; their version-8 configs declare `van`, `aan`, `cc` and
  `message_id`. The data and the schema disagree.
- **Let edit change the log type.** The type sits in the entry name, so it is a
  rename. The add form has the control; edit does not.
- **Stop resolving fields by key name.** `zaak_view.py:125` reads `contact_naam`,
  so a rename in the config drops the value from the page.
- **Name a dangling dossier ref in `odas check`.** A deleted zaak stays in
  `zaken:` and the page drops the row silently.
- **Resolve a document by log entry plus name** in `odas index summary` and
  `summarize`. Filename alone puts a summary beside the wrong copy.
- **Validate log frontmatter in `odas check`.** Undeclared keys pass today.
- **Split `1.3` from `1:3` in `slug_artikel`.** Both become `artikel_1-3`.
- **One wording for every mail refusal** in `naming.py`. Two texts let a stranger
  probe which refs exist.
- **Make a ref hard to guess.** Every sender may write to a zaak address, so the
  ref is the only gate, and `handle_RCPT` answers 250 for a real one over 90.000 `zk-NNNNN`
  addresses. Widen `mint_ref`, or answer 250 to every well-formed ref. Pairs
  with the item above.
- **Guard the Team link on team membership**, not on having an email. A grantee
  is offered it and gets a 403.
- **Publish an MTA-STS policy.** TXT record plus a static file, in the deployment repo.

## Shape

- **Delete the raw `index.md` editor**, plus `parse_or_raw`, `reopen_raw` and the
  vendored CodeMirror.
- **Move create and edit into the application layer.** They still sit in routes.
- **Move the intake body template into config.** `_body_template` and
  `_CONTEXT_LABELS` in `zaak_create.py`; retires `org.action_label`.
- **Delete the spent migrations** in `scripts/`. Every step up to layout 8 has
  run on both volumes. `upgrade.py` names them, so cut the table rows with them.
- **Rename `index_write.py` to `zaak_write.py`.** It sits beside `index.py`,
  which is a different meaning of "index".
- **Fold one-caller abstractions back**: `edit_handlers`, `log_handlers`,
  `folder_store.load_safe` take callbacks for a route that is gone.
- **Delete `is_team_member`** or give it a reader.
- **Rename the Dutch route verbs**: `bewerken`, `bijlage`, `relatie`,
  `indienen`. `/inzien-{token}` stays.

## Later

- **Full text search.** SQLite FTS5 behind `odas index sync`, plus an OCR
  backfill. The extraction cache exists.
- **Stop hashing every attachment per render.** `documents_of` reads each file
  whole; a path-to-hash lookup needs its own staleness rule.
- **Move a misfiled log entry to another zaak.** One danger-zone row plus a move
  between two `log/` folders.
- **Mint a value for a plain `token` field.** Only `reply_token` mints today.
- **File an Outlook `winmail.dat` properly.** Test against real Exchange first.
- **Add a PDF with a text layer to `tests/data/`.** Never a scan.

## Refused

- Sorting on "laatst bewerkt": not a fact on disk.
- A month separator: the `aangemaakt:` term answers it.
- Refs counted per year: a ref is random and already mailed out.
- A text field for the town: `locatie` holds lat/lon; the map answers it.
- An afwijzing as a status: it belongs with `zwaarte`, else two end states.

## Accepted

- A pocket-id outage locks out `toegang` grantees too.
- Map tiles come from `tile.openstreetmap.org`; `test_assets.py` names the host.
- The mail log records the relay's hop, not the sender's. Both facts survive in
  the `Received:` header inside `bericht.eml`.
- Nothing reads the prullenbak back; a person on the disk restores or clears it.
- A stamp without a zone (written before layout 12) is read as org time. A data
  dir that ran on a UTC server holds UTC there, so those old dates can be off by a day
  around midnight.
