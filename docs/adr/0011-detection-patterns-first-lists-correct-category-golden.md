# ADR-0011 — Categories are detected by patterns first, corrected by lists, and locked by a category golden

**Status:** Accepted (2026-09-14) · **Ticket:** [#4](https://github.com/mattiasthalen/deck-composer-v2/issues/4)

## Context

Soft metrics (ramp, draw, removal) and bracket caps (tutors, mass land denial, extra turns) both rest on deciding which cards belong to a category. The ticket asked whether detection is keyword and oracle-text heuristics or curated tag lists, and how a wrong detection is corrected. External decks (#8) bring cards nobody here has seen. Scryfall's tagger data is not in the card payload the catalog stores, and A2 says Scryfall is the only card data source. Rule 2 of #1: soft metrics are code, judgment is the composer's.

Rough pattern counts on the owned collection, 2026-09-14: 102 draw, 75 removal, 33 ramp, 11 "search your library" of which most fetch lands.

## Decision

**Patterns first, lists to correct.** A category is defined in the rules file (ADR-0010) by patterns; `include` and `exclude` lists by exact name override them. Rejected: curated lists alone, which cannot see a friend's card nobody listed and would need six hundred names hand-tagged; heuristics in code, where every correction is a release.

**The baseline is a category golden.** Over the test fixture's catalog, the membership list per category, reviewed by hand once at implementation and locked. A pattern edit shows as a diff and fails the test until the golden is regenerated on purpose. At run time every category metric lists the cards it counted, so a wrong detection is visible on every analysis. Rejected: a labelled corpus with measured precision and recall; nobody here maintains one.

**Corrections go into the rules file, never code and never deck files.** A name into `exclude` or `include`, version bumped, rerun.

**Cap categories lean toward recall, metric categories toward precision.** A false positive on a cap is a visible violation fixed by one exclude; a false negative is silent. Over-counting a metric distorts a target quietly. Each category's `source` note says which way it errs.

**Drift is accepted.** `cards refresh` reports every oracle text change by name; a changed text can move a card in or out of a category, the same staleness A22 already accepts.

## Consequences

- Unseen cards get pattern detection only; that is the point of patterns over lists.
- Land fetch is excluded from tutors by a negative pattern, not a list of fetch cards.
- Regenerating the golden is a deliberate step in the same commit as the pattern edit.
- Pattern quality is reviewed by the owner through the golden, not measured.
