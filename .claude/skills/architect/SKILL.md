---
name: architect
description: "Maintain the target design: ARCHITECTURE.md (one page) plus one document per subject in docs/design/. Overrides the global architect skill."
---

# Architect (ODAS)

`/architect <subject>` — write or update the target design. On PO request only.

The design is split so each part stays short enough to maintain. A long document
is not maintained, and an unmaintained document is worse than a missing one.

## The map

| File | Budget | Holds |
|------|--------|-------|
| `ARCHITECTURE.md` | 100 lines | Purpose, the one property, tiers, one diagram, the stack, the six system-wide decisions, non-goals, links |
| `src/odas/builtin/handleiding.md` | 120 lines | The core workflow, in Dutch, on the page a person reads |
| `docs/design/<subject>.md` | 120 lines | Why that subject is this way |
| `wip/backlog.md` | — | Every gap between the code and the target |

`ARCHITECTURE.md` may link to a design document. It may not restate one.

**If a sentence says what happens, it belongs in the manual.** A design doc
never retells the manual. This skill does not write the manual; it is Dutch
prose in one compact file.

## Rules

1. **One subject per file, 120 lines maximum.** Over the limit means the subject
   is two subjects, or the text describes code. Split it or cut it.
2. **Three sections, in this order.** A subject covered by the core workflow
   opens with one line naming `src/odas/builtin/handleiding.md`, then:
   - `## The model` — the nouns, and the rules that hold between them. A
     sentence here that describes the core workflow belongs in the manual instead.
   - `## What declares it` — the `.app/config.yaml` section, with a short YAML
     example. Configuration is the design surface of this app, so YAML is allowed.
   - `## Not this` — what the design refuses, and what that refusal beat. A
     refused alternative describes a screen that does not exist, so it can
     never duplicate a chapter.

   Do not duplicate the manual's Dutch prose in English.
3. **The target, not the state.** Never write a `## Deviations` section. A gap
   between code and target is a line in `wip/backlog.md`.
4. **No code, no function names, no file paths.** One exception per document: a
   closing `Seams:` line naming at most three modules. A path in prose is the
   drift this split repairs.
5. **A diagram instead of the paragraph that describes it, never both.** Mermaid
   only.
6. **Be specific.** Real names, real versions. No best-practice filler, and no
   deployment, observability or security boilerplate unless it shapes the design.
7. **Delete what is no longer true.** Preserve decisions that still hold.

## Process

1. Read `ARCHITECTURE.md`, the design document for the subject, the manual,
   and enough code to ground the discussion.
2. Discuss the change with the PO. Ask only when the answer changes the design.
   Flag an assumption as `[ASSUMPTION]`.
3. Write. Then add a new document to the table in `docs/design/README.md` and in
   `ARCHITECTURE.md` §4. A core-workflow behavior change goes to the manual first, and the
   PO approves that diff; this document then follows without a second stop.
4. Report the line count of every file you touched.

## A new subject

Add a document when a subject has its own UX **and** its own rule set. Until
then, a proposal lives in `wip/`. When the PO decides it, the decided design
becomes a brief document here and the proposal stays in `wip/` as the record.
