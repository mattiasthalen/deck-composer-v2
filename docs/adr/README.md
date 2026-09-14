# Architecture Decision Records

This directory holds Architecture Decision Records (ADRs) in Michael Nygard's
lightweight format: a short **Context / Decision / Consequences** note per
decision, with a **Status**.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-argparse-cli-json-only-output.md) | Tools are argparse subcommands of one CLI and emit JSON only | Accepted |
| [0002](0002-collection-single-json-file-schema-regenerated.md) | The collection is one sorted JSON file with an integer schema, regenerated rather than migrated | Accepted |

## Conventions

- This index is the canonical list of ADRs; keep it in step with the files.
- Filenames: `NNNN-kebab-case-title.md`, numbered sequentially.
- Status is one of: Proposed, Accepted, Deprecated, Superseded.
- An ADR records a decision and why; it is not updated when the decision is
  implemented. Supersede it with a new ADR if the decision changes.
- The `Ticket` field on the status line names the issue whose design interview
  produced the decision.
