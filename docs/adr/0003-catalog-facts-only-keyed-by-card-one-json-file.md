# ADR-0003 — The catalog holds Scryfall facts only, keyed by card with printings nested, in one JSON file under the collection-file convention

**Status:** Accepted (2026-09-14) · **Ticket:** [#3](https://github.com/mattiasthalen/deck-composer-v2/issues/3)

## Context

The system design (#1) split authority: the collection is authoritative for ownership, the catalog for card facts. It defined the catalog as "Scryfall-derived data for every card the project has seen, owned or not, with owned quantity". Composition, singleton and every deck reference use the card, the exact Scryfall name; the collection references printings, Scryfall IDs, one per lot. The analyzer (#4) joins the catalog by name; the table store (#6) and artifacts (#7) need token ownership and per-binder quantities; the composer (#5) reads a derived view.

Measured 2026-09-14: 603 cards, 676 printings, 34 token printings. Scryfall gives distinct tokens distinct oracle_ids, and the token "Splash Lasher" shares its name with the card "Splash Lasher". ADR-0002 fixed the convention for committed data files: one sorted JSON document with an integer `schema`, readers fail loudly on an unknown value, regeneration instead of migration.

## Decision

**The catalog carries no ownership.** It holds card facts and nothing else; owned quantity and "owned or not" are computed where they are needed, at view build, from the collection. The lexicon entry for catalog changes accordingly. Rejected: keeping owned quantity in the catalog as #1 defined it. It is a copy of what the collection already holds, and it is stale from the moment an ingest runs until the next catalog build, so two committed files would each claim ownership.

**Keyed by card, with the printings seen nested under each card.** One entry per exact Scryfall name carries the oracle-level facts; a list under it carries each printing the project has seen with its Scryfall ID, set, set type, collector number, rarity and release date. Rejected: keyed by printing. Every consumer references cards, never printings; a printing key duplicates the oracle facts per printing and forces an index for the lookup every caller makes.

**Tokens and other never-candidates live in their own section keyed by oracle_id.** Names do not identify tokens: tokens share names with the cards that make them and with each other. Cards link their related tokens by oracle_id; a token is owned when any lot's printing carries that oracle_id. Which objects are tokens is decided by the Scryfall layout alone, from a closed vocabulary that maps every known layout to card or token; an unknown layout fails enrichment loudly, the posture ADR-0002's binder types set. Rejected: treating an unknown layout as a card. It is silent drift, and rule 6 of #1 says drift fails loudly.

**Two invariants are enforced at every build and fail it.** A lot's name equals the catalog name for its Scryfall ID (assumption A15); within the cards section one name maps to one oracle_id (A19). Rejected: warning and mapping lots to cards through the ID. Sum-by-name in the collection module works on the exported name, so a tolerated mismatch gives two answers for one card's ownership.

**Coverage is checked directly; the catalog records no collection hash.** Any operation that joins collection and catalog checks that every lot's printing is present and fails or fetches on a gap. The catalog is a union over time, never a snapshot of one collection; the view is the snapshot and records the collection hash it was built from. Rejected: a collection hash in the catalog as a staleness flag. It is indirect, and it is wrong the moment a name-only card is added.

**One file, `data/catalog.json`, under the ADR-0002 convention.** Integer `schema`, one card per line sorted by name, tokens likewise by oracle_id, a custom writer locked by a byte-exact golden, all-or-nothing writes, no migration code. Rejected: one file per card. Thousands of files with names derived from card names that contain `//` and commas, readers that glob, slower git. Rejected: JSONL, already rejected in ADR-0002 for the same reasons.

## Consequences

- Ownership has exactly one home. The view, the analyzer's budget and verify all derive it from the collection; the catalog can be rebuilt or refreshed without touching ownership.
- Rarity and set have no card-level value. A consumer wanting "the set" reads the owned printing's set from the lot, or the printings list.
- A rename on either side, ManaBox or Scryfall, stops enrichment until an alias map exists. None exists today; the resolution path is recorded on A15 and built when it fires.
- Regenerating the catalog needs the network, unlike the collection: at ten times today's size about a hundred requests. At that size the file is around ten megabytes, one document, no partial read.
- Names known only from past resolves, unowned cards on maybeboards, return to a regenerated catalog on the next resolve, not the regeneration itself.
- A new Scryfall layout blocks enrichment until a one-line vocabulary change, the accepted cost of failing loudly.
