# ADR-0012 — The analyzer is one read-only operation whose violations are success output, estimating every deck's bracket, in three modules

**Status:** Accepted (2026-09-14) · **Ticket:** [#4](https://github.com/mattiasthalen/deck-composer-v2/issues/4)

## Context

Rule 1 of the system design (#1): the analyzer is the floor; artifacts are written only from decks it has passed. ADR-0001: one subcommand per module, success is one JSON object on stdout at exit 0 with `next`, exit 1 is reserved for contract failure, exit 2 for usage. The ticket: violations block, metrics inform. The composer's loop builds against the analyzer until no violations remain, then reviews against metrics, every pass. The table store (#6) owns the table directory layout and must exclude cards allocated to other tables; deck origins (#8) needs an external deck's bracket. The repo has one module per committed file format.

## Decision

**One operation, `analyze DECK [DECK...]`.** The deck files handed to one call are the table context. Flags: `--bracket`, `--exclude-binder` (repeatable, the meaning `cards enrich` gives it), `--reserve DECK` (repeatable, a deck that consumes the budget by its origin and is not analyzed), `--theme` (repeatable, `set:CODE` or `type:SUBTYPE`), and the usual path overrides. The analyzer never reads a table directory. Rejected: `--table DIR`, which leaks #6's layout into #4; a `check` operation for rules and an `analyze` for metrics, when metrics cost nothing offline and the loop wants both every pass; a separate `compare`, which is a section of the same result.

**Violations are success output.** Exit 0, `passed` per deck and for the table, `next` naming the deck to fix first or saying the table passes. Exit 1 stays contract failure: an unreadable deck or rules file, a missing catalog or collection, an unknown binder or bracket, a deck file repeated or both reserved and analyzed. Rejected: a third exit code for "violations found"; the caller is a model reading JSON, and a new code widens the contract of every tool.

**Every bracket is evaluated for every deck.** `bracket.estimated` is the lowest bracket whose caps the deck meets and lists the criteria lifting it past each lower one; violations are raised against `--bracket` only, and no `--bracket` means estimate only.

**Budget is one table-level rule and every allocating deck fails it.** Rule 1 needs a per-deck answer; the composer decides who gives the card up, never the analyzer.

**Read-only and deterministic.** No file is written; the same inputs give the same bytes; the only time-dependent output is the refresh advisory, which takes an injectable date.

**Three modules.** `deck.py` owns the deck file, `rules.py` the rules file, `analyzer.py` the rules and metrics logic together with the operation. Rejected: everything in one module, which mixes two file formats with the logic; splitting logic from operation, a pass-through layer for one caller.

## Consequences

- The composer reads one JSON object per pass. Adding a rule or a metric never changes the exit contract.
- The table store implements exclude-by-table by passing another table's built and owned deck files as reserved decks.
- The output grows with decks, metrics and listed cards; at four decks it is a few hundred names.
- A rerun after any failure is always safe.
- CLAUDE.md's module table gains three rows.
