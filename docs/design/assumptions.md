# Assumptions record

Standing assumptions the design depends on, each with the observation that would show it stopped holding, plus the facts the project has measured. Maintained by design interviews. The system design that produced the first entries is issue #1; the scaffold and ingest interview (issue #2) added A15 to A18 and the second block of measured facts.

An assumption is a statement the design treats as true without the code enforcing it. When one stops holding, every branch that hangs off it needs a second look, so each entry names the observation that would falsify it.

## Standing assumptions

| ID | Assumption | Area | Status | You would know it stopped holding when |
|---|---|---|---|---|
| A1 | Every ManaBox export row carries a Scryfall ID. | Ingest | Verified on 869 of 869 rows, 2026-09-14 (#1, re-checked in #2) | A row without one, such as a custom or proxy card. Ingest fails loudly. |
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
| A15 | The ManaBox Name column equals the exact Scryfall name. | Ingest, card data | Verified on 869 of 869 rows against Scryfall by ID, 2026-09-14 | Card data reports a lot whose name differs from the catalog name for its Scryfall ID. The collection keeps the exported name; the catalog is authoritative. |
| A16 | Every export is the whole collection, never a single binder. | Ingest | Owner practice. ManaBox allows per-binder export; the owner never uses it | A change report showing mass removals. Re-export the whole collection and ingest again. |
| A17 | Cards placed in ManaBox decks appear in the collection export with Binder Type `deck` and the deck's name as Binder Name. | Ingest, table store, composer | Verified 2026-09-14 on a second export: the deck "Wick, the Whorled Mind" appears as 70 rows of type `deck`; the cards left the binder rows, total cards unchanged | A re-export after creating a ManaBox deck lacks those rows or carries another type. |
| A18 | The Added timestamp is stable per row across exports. | Ingest | Holds across two exports: 0 of 813 lots present in both changed Added | A re-export whose diff changes Added on otherwise unchanged lots. Then drop the column; the lot key already excludes it. |

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

Source: the same export, profiled during the scaffold and ingest interview (issue #2), 2026-09-14.

| Fact | Value |
|---|---|
| Encoding and line endings | ASCII, no BOM, CRLF |
| Foil values | normal 774, foil 95 |
| Condition values | mint 457, near_mint 412 |
| Language values | en only |
| Binder Type values | binder only |
| Misprint, Altered | false on every row |
| Added format | ISO-8601 UTC instant with milliseconds and `Z`; range 2026-07-22 to 2026-08-26 |
| Quantity | integers 1 to 15 |
| Set code case | uppercase in the export, lowercase on Scryfall; identical after lowercasing |
| Collector numbers | all numeric, identical to Scryfall |
| Duplicate lot keys | 0; no two rows share Scryfall ID, foil, condition, language and binder |
| ManaBox ID | one per printing, 676 distinct |
| Names containing commas | 23 |
| Names containing `//` | 25 rows, 24 names; layouts prepare 20 rows, transform 5 |
| Layouts of owned printings | normal 608, token 34, prepare 19, class 9, transform 5, case 1 |
| T-prefixed set codes | 8. TBLB, TFDN, TINR, TMKM, TSOC, TSOS are token sets; THS and TDM are expansions, so the prefix is not a token test |
| Purchase price | empty on 13 rows; currency SEK |

Source: the owner's second export, 2026-09-14, after moving a deck into ManaBox. Ingested as collection hash `sha256:247cce4524b28f3764be2acb82de99c970a73abd71f0cfe2937f278b864a49ba`.

| Fact | Value |
|---|---|
| Rows / physical cards / distinct names | 883 / 1354 / 603 |
| Binders | 2: "OmniHive: Secrets of Strixhaven" (`binder`, 813 rows, 1,284 cards) and "Wick, the Whorled Mind" (`deck`, 70 rows, 70 cards, 70 names) |
| Header, encoding, line endings | identical to the first export |
| Change report against the first export | lots added 70, removed 56, quantity changed 14; names added 0, removed 0, quantity changed 0; cards delta 0 |
| Printings split between the binder and the deck | 14 |
| Added values on lots present in both exports | unchanged, 813 of 813 |
