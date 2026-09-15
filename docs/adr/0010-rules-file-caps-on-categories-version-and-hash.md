# ADR-0010 — Bracket rules and targets are caps on categories in one hand-edited rules file with a declared version and a content hash

**Status:** Accepted (2026-09-14) · **Ticket:** [#4](https://github.com/mattiasthalen/deck-composer-v2/issues/4)

## Context

Rule 5 of the system design (#1): bracket criteria beyond the Scryfall Game Changer flag live in a versioned rules file in the repo, and a table records the rules version it was built under. WotC's bracket definitions evolve (A5); Scryfall's `game_changer` flag can lag WotC's list (A13). The ticket asked where reference targets per bracket live, what the file's schema is and how versions are named. Deck origins (#8) needs an external deck's bracket estimated from the same rules.

Measured 2026-09-14 on the owner's collection: 1 Game Changer (Vampiric Tutor), 0 extra-turn cards, 0 mass land denial, 11 "search your library" cards, most of them land fetch. ADR-0002's convention applies to committed data files.

## Decision

**One file, `data/rules.json`, hand-edited.** Integer `schema`, fail-loud reader, `format` (`commander`), `version` as an ISO date the owner bumps on every edit, `source` naming the WotC document and the date it was read. The analyzer reports `rules_version` and `rules_hash`, the sha256 of the file's bytes, so an edit nobody bumped is visible to the table store. A schema bump means the owner rewrites a small file; nothing regenerates it. Rejected: constants in code, where every change is a release and rule 5 forbids it; the git blob hash as the version, opaque in table metadata; a rules directory for one file.

**Categories are named card sets** defined by the `game_changer` flag, keywords, type-line and oracle-text patterns, negative patterns, and `include` and `exclude` lists of exact names, matched over every face with reminder text removed. `include` and `exclude` are A13's override and the correction path for a wrong detection. A listed name the catalog lacks is accepted silently, since the file may name unowned cards.

**A bracket is a set of caps on categories**: `{category: max}`, where 0 forbids and an absent category is uncapped. Brackets 4 and 5 carry no caps, so every deck meets them. Every deck is evaluated against every bracket; the lowest it meets is its estimated bracket, and violations are raised against the requested bracket only. Rejected: richer predicates such as "extra turns may not chain"; chaining is judgment, and a count is the deterministic floor the composer reasons from.

**Targets live in the same file**, per bracket, per metric, as `[min, max]`, with optional spread targets across a table. A metric without a target reports "no target". Rejected: targets in code; a second file, which is a second version for every table to record.

## Consequences

- A table records one version and one hash. A bracket definition change is a data edit reviewed in git diff, and an old table still says which opinion it was built under.
- `bracket_unknown` when `--bracket` names a bracket the file lacks; a criterion or target naming an unknown category or metric fails the read.
- A typo in an include or exclude list cannot be detected offline; accepted.
- A pathological pattern from a hand edit can hang the analyzer; patterns compile at read and nothing more, accepted because the file is the owner's own.
- The composer may propose an edit in-session; the owner confirms, because the rules are the owner's opinion and every table records the version.
