# Backlog

Known defects and accepted limits. Nothing is scheduled.

## Defects

- **A zaak ref is easy to guess.** Any sender can mail a zaak address, and
  `handle_RCPT` tells a real ref from a false one. Widen `mint_ref` and use one
  refusal text in `naming.py`.
- **`odas wetten add` finds 0 articles in the Burgerlijk Wetboek.** Fix `wetten.py`.
- **`tests/data/` log entries use `bcc` and `verzonden`**, which their configs do
  not declare.

## Accepted limits

- A pocket-id outage also locks out `toegang` grantees.
- Map tiles come from `tile.openstreetmap.org`.
- Nothing reads the prullenbak back. A person on the disk restores or clears it.
