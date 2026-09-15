# Architecture Decision Records

This directory holds Architecture Decision Records (ADRs) in Michael Nygard's
lightweight format: a short **Context / Decision / Consequences** note per
decision, with a **Status**.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-argparse-cli-json-only-output.md) | Tools are argparse subcommands of one CLI and emit JSON only | Accepted |
| [0002](0002-collection-single-json-file-schema-regenerated.md) | The collection is one sorted JSON file with an integer schema, regenerated rather than migrated | Accepted; per-card ownership consequence superseded by ADR-0013 |
| [0003](0003-catalog-facts-only-keyed-by-card-one-json-file.md) | The catalog holds Scryfall facts only, keyed by card with printings nested, in one JSON file under the collection-file convention | Accepted; token classification superseded by ADR-0008 |
| [0004](0004-scryfall-collection-endpoint-not-bulk-data.md) | Card data fetches through Scryfall's collection endpoint, never bulk files | Accepted |
| [0005](0005-collection-view-uncommitted-tsv-grep-filter-path.md) | The collection view is an uncommitted TSV rebuilt by every card-data operation; grep is the filter path | Accepted |
| [0006](0006-explicit-refresh-rank-two-significant-figures.md) | Catalog refresh is an explicit whole-catalog operation, and edhrec_rank is stored at two significant figures | Accepted |
| [0007](0007-name-resolution-exact-in-tool-judgment-in-composer.md) | Name resolution is exact in the tool; typo judgment stays with the composer | Accepted |
| [0008](0008-token-set-type-marks-a-token.md) | A printing in a token set is a token, whatever layout Scryfall gives it | Accepted |
| [0009](0009-deck-file-json-per-deck-schema-bump-rewrites-tables.md) | The deck file is one JSON file per deck, and a schema bump rewrites every table in one commit | Accepted |
| [0010](0010-rules-file-caps-on-categories-version-and-hash.md) | Bracket rules and targets are caps on categories in one hand-edited rules file with a declared version and a content hash | Accepted |
| [0011](0011-detection-patterns-first-lists-correct-category-golden.md) | Categories are detected by patterns first, corrected by lists, and locked by a category golden | Accepted |
| [0012](0012-analyzer-one-operation-violations-exit-zero-every-bracket-estimated.md) | The analyzer is one read-only operation whose violations are success output, estimating every deck's bracket, in three modules | Accepted |
| [0013](0013-ownership-per-card-joins-through-printings.md) | Ownership per card is a join through printings in the catalog module; sum by name counts lots | Accepted |

## Conventions

- This index is the canonical list of ADRs; keep it in step with the files.
- Filenames: `NNNN-kebab-case-title.md`, numbered sequentially.
- Status is one of: Proposed, Accepted, Deprecated, Superseded.
- An ADR records a decision and why; it is not updated when the decision is
  implemented. Supersede it with a new ADR if the decision changes.
- The `Ticket` field on the status line names the issue whose design interview
  produced the decision.
