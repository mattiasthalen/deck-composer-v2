# ADR-0006 — Catalog refresh is an explicit whole-catalog operation, and edhrec_rank is stored at two significant figures

**Status:** Accepted (2026-09-14) · **Ticket:** [#3](https://github.com/mattiasthalen/deck-composer-v2/issues/3)

## Context

The catalog is authoritative for card facts (ADR-0003), and some facts move: commander legality when a card is banned or unbanned, the Game Changer flag when WotC revises the list (A13), oracle text on errata, and edhrec_rank, which changes daily for most cards. Rule 4 of #1 makes the tools offline first, and ADR-0002 makes git diff the review tool for every committed data file. The analyzer (#4) wants a power proxy from edhrec_rank, a soft metric.

## Decision

**Refresh is explicit.** `cards refresh` re-fetches every catalog entry, tokens included, writes the catalog, and reports what changed: legality flips, Game Changer flips, text changes, renames, entries Scryfall no longer returns. Enrichment never touches an existing entry. The catalog carries one file-level `refreshed` date, null until the first refresh, and no entry is ever older than it. Rejected: refreshing entries past a certain age automatically during a build. It hides network use inside an operation the owner expects to work offline, and it makes a build's output depend on the calendar.

**edhrec_rank is stored at two significant figures.** 9518 becomes 9500, 22870 becomes 23000, 120 stays 120. Rejected: the raw rank. It changes for most cards on every refresh, so every refresh rewrites most lines and the diff shows nothing else. Rejected: fixed buckets of a thousand. Coarse exactly at the top of the ranking, where power differences matter.

**Only commander legality is stored**, one of legal, not_legal, banned, restricted. No other format is played (#1 non-goals).

## Consequences

- Between refreshes the catalog can be wrong about legality and the Game Changer flag; assumption A22 records this, with "refresh before composing when online" as the mitigation. The tool does not decide when the owner has been offline long enough.
- A refresh diff is readable: a line changes when a fact changed, and ranks move only when a card's standing moved about five percent.
- The rank the analyzer sees has declared precision. A metric that needs finer resolution than two significant figures argues this ADR, not the data.
- A rename found by refresh is written as truth; the next join fails on the name invariant (ADR-0003) until an alias exists.
- A second format would add a legality field per format, within the schema, not a format switch.
