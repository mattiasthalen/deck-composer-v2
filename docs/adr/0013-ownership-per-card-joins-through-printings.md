# ADR-0013 — Ownership per card is a join through printings in the catalog module; sum by name counts lots

**Status:** Accepted (2026-09-14) · **Supersedes:** part of [ADR-0002](0002-collection-single-json-file-schema-regenerated.md), the consequence that per-card ownership calls sum by name · **Ticket:** [#4](https://github.com/mattiasthalen/deck-composer-v2/issues/4)

## Context

ADR-0002 gave the collection module a sum by name and said consumers needing per-card ownership call it. ADR-0003 put tokens in their own catalog section keyed by oracle_id because tokens share names with cards. Measured 2026-09-14: eight token lots from the Bloomburrow token set share a card's name; "Splash Lasher" is 3 by name and 1 as a card. The collection view already joins each lot through its printing (`Catalog.owner_of`) and gets it right. The analyzer's budget (#4), verify (#6) and the pull list (#7) would have called the sum by name and got it wrong.

## Decision

**Owned quantity per card is a join through each lot's printing, in `catalog.py`**, beside `missing_printings` and `name_mismatches`, which already answer what a collection looks like against the catalog. It returns, per card, the quantity per binder name and type pair; a total under binder exclusion is a sum over it. The view switches to it, locked by its existing golden. Rejected: `collection.py`, which does not know the catalog and must not; `view.py`, a rendering module; `analyzer.py`, a second copy of the view's join; filtering token names out of the sum by name, since a token and a card can share a name, the reason ADR-0003 keyed tokens by oracle_id.

**`owned_by_name` and `owned_by_binder` stay lot-level sums by name**, what the change report compares, documented as not ownership per card. The pull list uses the join.

## Consequences

- One join, three consumers: the view, the budget, verify and the pull list.
- Per-card ownership needs the catalog to cover every lot, which every consumer already requires.
- ADR-0002's guidance to consumers changes; its file format and change report are untouched.
