# Assumptions record

Standing assumptions the design depends on, each with the observation that would show it stopped holding, plus the facts the project has measured. Maintained by design interviews. The system design that produced the current entries is issue #1.

An assumption is a statement the design treats as true without the code enforcing it. When one stops holding, every branch that hangs off it needs a second look, so each entry names the observation that would falsify it.

## Standing assumptions

| ID | Assumption | Area | Status | You would know it stopped holding when |
|---|---|---|---|---|
| A1 | Every ManaBox export row carries a Scryfall ID. | Ingest | Verified on 869 of 869 rows, 2026-09-14 | A row without one, such as a custom or proxy card. Ingest fails loudly. |
| A2 | Scryfall is the only card data source needed. | Card data | Holds. Combos are composer judgment; bracket lists beyond the Game Changer flag live in the local rules file. | A rule needs data Scryfall lacks. |
| A3 | One table is sleeved at a time, so tables are independent selections from the whole collection. | Table store | Confirmed by the owner | Two tables sleeved at once. Use the exclude-by-table scoping filter. |
| A4 | Basic lands are tracked in the export in real quantities. | Ingest, analyzer | Verified, 223 basics | n/a |
| A5 | WotC Commander Bracket definitions evolve. | Analyzer | Hedged: rules are versioned data | n/a |
| A6 | Decks at a table should be balanced against each other. | Composer | Confirmed as a review criterion, not a gate | n/a |
| A7 | The collection stays within ten times today's size (603 distinct names). | Card data, composer | Holds | The collection view no longer fits in one context window. Use the filter path. |
| A8 | Tokens and emblems are never deck candidates. | Card data | Confirmed | A format that lists tokens. |
| A9 | Composition identity is the card name; foil and condition are irrelevant. | Data model | Confirmed | Foil-only or condition-aware requests. |
| A10 | Built decks are handed to other players, so the playbook targets a pilot who has never seen the deck. | Artifacts | Inferred during capture, not confirmed by the owner | The owner says playbooks are for themself only. |
| A11 | The ManaBox deck import format is: a `// COMMANDER` section, mainboard lines, optional `// SIDEBOARD` and `// MAYBEBOARD` sections, each line `N Name`. | Artifacts | Stated by the owner | A failed import. Verify by hand after every format change. |
| A12 | "A good match" against given decks means a fair opponent at the table's level, not a hard counter. | Composer | Confirmed by no objection | The owner asks for counters by default. |
| A13 | Scryfall's `game_changer` flag tracks WotC's Game Changer list. | Analyzer | Field verified present, 2026-09-14 | WotC updates the list and Scryfall lags. The rules file can override. |
| A14 | No partner or Background commanders are owned, so the analyzer's commander check handles single commanders only. | Analyzer | Verified against the 2026-08-26 export | A partner or Background card enters the collection. The check is written so adding them is a local change. |

## Invalidated

Assumptions that stopped holding, kept so nobody re-derives them.

| ID | Assumption | Replaced by | When |
|---|---|---|---|
| X1 | The tool makes no cards-to-buy recommendations. | No price awareness and no shopping lists. Unowned upgrades are in scope as the maybeboard. | #1, 2026-09-14 |
| X2 | Tables must be disjoint from each other. | Tables are independent selections; disjointness holds within a table. One table is built at a time. | #1, 2026-09-14 |

## Measured facts

Source: the owner's ManaBox collection export dated 2026-08-26, resolved against Scryfall on 2026-09-14.

| Fact | Value |
|---|---|
| Rows / physical cards / distinct names | 869 / 1,354 / 603 |
| Printings, all resolved by Scryfall ID | 676, zero misses |
| Commander-legal printings | 640, plus 1 banned (Prophet of Kruphix) and 1 not legal |
| Token and emblem printings | 34 |
| Legendary creatures, the commander candidates | 24, none with partner |
| Nonbasic land names | 19 |
| Basics | 223: Plains 40, Island 49, Swamp 38, Mountain 42, Forest 54 |
| Game Changers owned | 1, Vampiric Tutor |
| Distinct Bloomburrow card names | 229, and 48 percent of all cards by quantity |
| Binders | 1, "OmniHive: Secrets of Strixhaven" |
| Names containing `//` | 25 |
| Scryfall collection endpoint | Resolves 75 identifiers per request; the whole collection took 10 requests |
| Export columns | Binder Name, Binder Type, Name, Set code, Set name, Collector number, Foil, Rarity, Quantity, ManaBox ID, Scryfall ID, Purchase price, Misprint, Altered, Condition, Language, Purchase price currency, Added |
