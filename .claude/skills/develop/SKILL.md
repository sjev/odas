---
name: develop
description: "Deliver a feature test-first: one core test, one PO gate, then implement to green without stopping. Overrides global develop skill."
---

# Develop (ODAS)

`/develop <description>` — deliver one behavior change. Read `CLAUDE.md` for testing rules.

Document in `handleiding.md` only what a person cannot see on screen. A trivial or
self-evident change gets no manual text; the core test is then the whole spec.

## Phase 0 — Branch
- `git checkout -b feat/<slug>` (plain slug, no issue numbers). Stash/pop dirty tree if needed.

## Phase 1 — Core Test (The Spec)
1. Find relevant file in `tests/` using the test map in `CLAUDE.md` (or add a new file if needed).
2. Write ONE core test: the happy path only. Follow the `CLAUDE.md` rules
   (+ example data under `tests/data/<profile>/` if data-shaped). No edge cases yet.
3. Run the test and verify it fails.
4. **STOP.** Show the test diff to the PO. This is the only gate.
   *(Only ask questions if the answer alters an assertion; otherwise choose the simpler behavior).*

## Phase 2 — Green (Run to the End)
After approval, work without stopping:
1. Add edge-case and error tests. Do NOT show these for review.
2. Write the minimal code to pass. Do NOT edit the approved test to make it pass.
3. Run `inv ci` until green. Commit with conventional messages.
4. Stop early only after 3 failed attempts at the same problem. Then report.

## Phase 3 — Hand-off
Report the `inv ci` result, then output:
> Branch `feat/<slug>` is ready. Test it, then run `/merge <slug>`.

## Deleting Behavior
Reverse the cycle, one gate: show the test deletion -> PO approval -> verify green suite ->
delete the code -> run `inv ci` -> commit.
