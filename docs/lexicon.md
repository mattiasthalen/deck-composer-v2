# Lexicon

The design vocabulary for deck-composer-v2. Every term here carries a meaning the design depends on. Use these words, and only these, in design discussions, tickets, code identifiers and documentation.

Maintenance rules, so the file stays useful:

- A term is admitted only when a design branch closes needing it, and only if getting it wrong would produce divergent implementations: it is overloaded, it names a distinction the code must preserve, a design decision defined it, or it will become an identifier.
- An entry that merely restates the ordinary meaning of a word is noise. Delete it.
- Target size is roughly 20 to 30 entries. Past that, adding one means arguing another out.
- Record where each entry came from, so a later reader can find the decision behind it.

Entries marked #1 come from the system design interview of 2026-09-14 (issue #1). Entries marked #2 come from the scaffold and ingest design interview of the same day (issue #2). Entries marked #3 come from the card data design interview of the same day (issue #3); two inherited entries changed there and say so.

| Term | Meaning | Since |
|---|---|---|
| table | One or more decks composed together from one collection snapshot under a shared ownership budget, sized for as many players as it has decks. A single deck is a table of one. The only persisted unit. | #1 |
| deck | A Commander list referenced by card name and quantity, with a commander and an origin, living in exactly one table. | #1 |
| origin | One of built, owned or external. Decides whether a deck consumes the budget, whether the composer may change it, and whether artifacts are produced for it. Built: composed here from the collection. Owned: a supplied list of the owner's cards. External: a list someone else brings. | #1 |
| collection | The normalized ownership record derived from one ManaBox export. Price removed, binder retained. Authoritative for ownership. | #1 |
| lot | One export row: a printing with foil, condition, language, binder and quantity. | #1 |
| printing | One Scryfall ID. | #1 |
| card | One exact Scryfall name, both faces included for double-faced cards. The unit of singleton and of every deck reference. Physical attributes never matter to composition. | #1 |
| catalog | Scryfall-derived facts for every card the project has seen, owned or not. Keyed by card, the exact Scryfall name, with the printings seen nested under each card; tokens keyed by oracle_id. Never carries ownership; a union that only grows. Authoritative for card facts. | #1, changed #3 |
| collection view | The derived one-line-per-owned-card TSV the composer reads, built from the collection and the catalog by every `cards` operation. Regenerable, never committed. | #1, changed #3 |
| composer | The Claude Code skill that interprets requests, chooses commanders, builds decks against the analyzer, reviews, presents and interviews the owner. | #1 |
| analyzer | The deterministic tool that returns violations and metrics for a deck or a set of decks. The floor beneath everything the composer asserts. | #1 |
| violation | A hard-rule failure with a reason. Blocks artifacts. | #1 |
| metric | A soft measurement with a reference target. Informs judgment, never blocks. | #1 |
| budget | Per card name, owned quantity minus copies allocated to built and owned decks of the same table. Tables are independent of each other. | #1 |
| swap list | Per deck, cards out and cards in, emitted by improve. Exists because decks are sleeved. | #1 |
| maybeboard | In this project, the decklist section holding unowned cards that would improve the deck. ManaBox's own meaning of the word is broader. | #1 |
| draft, accepted | Table states. Draft while composing and steering; accepted once the owner says so. Accepted tables change only through improve. | #1 |
| improve | The explicit operation that changes an accepted table and emits swap lists. | #1 |
| rules version | Identifier of the bracket and format rules file a table was built under. | #1 |
| export | The ManaBox collection CSV that ingest reads. Never committed. Not a decklist (artifacts produce those) and not a ManaBox deck export. | #2 |
| collection hash | sha256 of the raw export bytes, written into the collection file and copied into table metadata. Identifies an ownership snapshot independent of the collection file's format. | #2 |
| lot key | Scryfall ID, foil, condition, language, binder name and binder type. The identity the change report diffs on. Added is excluded. | #2 |
| change report | Ingest output comparing the new collection with the existing collection file by lot key. Never a comparison of two exports. | #2 |
| token | Anything Scryfall ships that can never be a deck candidate: tokens, double-faced tokens, emblems, art series, planar, scheme and vanguard cards. The Scryfall layout decides. Kept in the catalog's token section, excluded from the collection view; owned when any lot's printing shares its oracle_id. Wider than the game's own meaning. | #3 |
| enrich | The `cards` operation that fetches only what the catalog lacks for the current collection, never touching an existing entry, and rebuilds the collection view. Restores coverage: every lot's printing is in the catalog. | #3 |
| refresh | The `cards` operation that re-fetches every catalog entry and reports what changed. Restores freshness. Never automatic. | #3 |
| resolve | The `cards` operation that turns names into exact Scryfall names, from the catalog first and Scryfall second, reporting each miss with at most one suggestion that is never persisted. | #3 |
