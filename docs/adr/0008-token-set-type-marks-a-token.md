# ADR-0008 — A printing in a token set is a token, whatever layout Scryfall gives it

**Status:** Accepted (2026-09-14) · **Supersedes:** the token classification sentence of [ADR-0003](0003-catalog-facts-only-keyed-by-card-one-json-file.md) · **Ticket:** [#3](https://github.com/mattiasthalen/deck-composer-v2/issues/3)

## Context

ADR-0003 decided that which objects are tokens is decided by the Scryfall layout alone, from a closed vocabulary, and assumption A21 recorded the falsifier: a never-candidate arriving with a card layout. The first real catalog build on 2026-09-14 produced one. The Role token "Monster // Sorcerer" from the Wilds of Eldraine token set has layout `flip`, and a live check showed dungeons such as "Lost Mine of Phandelver" have layout `normal`. Both sit in sets whose `set_type` is `token`. Scryfall's `set_type` is its own set metadata, not the T-prefix heuristic on set codes that #2 measured to be wrong.

## Decision

**An object is a token when its layout is a token layout or its printing's `set_type` is `token`.** An unknown layout still fails loudly first; the closed vocabulary stands. Rejected: a type-line test, "Token" or "Emblem" as the first word. It misses dungeons, whose type line is "Dungeon". Rejected: `set_type` alone. Tokens are also printed in promo sets, and the layout catches those.

## Consequences

- Role tokens, dungeons, helper cards and everything else printed in a token set land in the catalog's token section and never in the view, whatever layout Scryfall assigns them.
- A real card printed in a set of type `token` would be misclassified. None is known; token sets hold none by construction.
- Classification reads one printing-level field. A token's every printing is in a token set, so the kind does not vary by printing.
- The catalog built before this decision carried one token as a card and was regenerated. A21 moved to the invalidated list as X3.
