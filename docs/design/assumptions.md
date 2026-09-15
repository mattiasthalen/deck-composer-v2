# Assumptions record

Standing assumptions the design depends on, each with the observation that would show it stopped holding, plus the facts the project has measured. Maintained by design interviews. The system design that produced the first entries is issue #1; the scaffold and ingest interview (issue #2) added A15 to A18 and the second block of measured facts; the card data interview (issue #3) added A19 to A22, sharpened A7 and A15, and added the Scryfall block of measured facts; A21 fell during the implementation the same day and moved to X3; the deck analyzer interview (issue #4) added A23 to A27 and the analyzer block of measured facts.

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
| A7 | The collection stays within ten times today's size (603 distinct names). | Card data, composer | Holds. The whole collection view (about 130 KB today) is estimated to fit one context window until roughly five times today's size (#3) | The collection view no longer fits in one context window. Use the filter path: grep and awk over the view inside the session. |
| A8 | Tokens and emblems are never deck candidates. | Card data | Confirmed. The catalog keeps every never-candidate in its token section, classified by Scryfall layout or token set type (ADR-0008); the view excludes them (#3) | A format that lists tokens. |
| A9 | Composition identity is the card name; foil and condition are irrelevant. | Data model | Confirmed | Foil-only or condition-aware requests. |
| A10 | Built decks are handed to other players, so the playbook targets a pilot who has never seen the deck. | Artifacts | Inferred during capture, not confirmed by the owner | The owner says playbooks are for themself only. |
| A11 | The ManaBox deck import format is: a `// COMMANDER` section, mainboard lines, optional `// SIDEBOARD` and `// MAYBEBOARD` sections, each line `N Name`. | Artifacts | Stated by the owner | A failed import. Verify by hand after every format change. |
| A12 | "A good match" against given decks means a fair opponent at the table's level, not a hard counter. | Composer | Confirmed by no objection | The owner asks for counters by default. |
| A13 | Scryfall's `game_changer` flag tracks WotC's Game Changer list. | Analyzer | Field verified present, 2026-09-14. `cards refresh` re-fetches it and reports flips (#3) | WotC updates the list and Scryfall lags. The rules file can override. |
| A14 | No partner or Background commanders are owned, so the analyzer's commander check handles single commanders only. | Analyzer | Verified against the 2026-08-26 export | A partner or Background card enters the collection. The check is written so adding them is a local change. |
| A15 | The ManaBox Name column equals the exact Scryfall name. | Ingest, card data | Verified on 869 of 869 rows against Scryfall by ID, 2026-09-14. Enforced at every catalog build since #3: a lot whose name differs from the catalog name for its Scryfall ID fails `cards enrich` with `name_mismatch` | A `name_mismatch` failure, most likely a rename on one side. The collection keeps the exported name; the catalog is authoritative. Resolution path, built only when it fires: a committed alias map from exported name to catalog name, read by card data. |
| A16 | Every export is the whole collection, never a single binder. | Ingest | Owner practice. ManaBox allows per-binder export; the owner never uses it | A change report showing mass removals. Re-export the whole collection and ingest again. |
| A17 | Cards placed in ManaBox decks appear in the collection export with Binder Type `deck` and the deck's name as Binder Name. | Ingest, table store, composer | Verified 2026-09-14 on a second export: the deck "Wick, the Whorled Mind" appears as 70 rows of type `deck`; the cards left the binder rows, total cards unchanged | A re-export after creating a ManaBox deck lacks those rows or carries another type. |
| A18 | The Added timestamp is stable per row across exports. | Ingest | Holds across two exports: 0 of 813 lots present in both changed Added | A re-export whose diff changes Added on otherwise unchanged lots. Then drop the column; the lot key already excludes it. |
| A19 | One exact Scryfall name maps to one oracle_id among cards with a card layout. | Card data | Holds for every card seen. Enforced at every catalog build: a collision fails `cards enrich` with `name_collision` | A `name_collision` failure. Known offenders: Unstable variants such as Everythingamajig, six different cards under one name, none owned. Resolution then: a disambiguation rule, decided when it happens. |
| A20 | Scryfall's collection endpoint resolves every owned printing by Scryfall ID and every exact name. | Card data | Verified 676 of 676 printings, 2026-09-14 | A `printing_not_found` failure on an owned lot, typically a printing Scryfall merged or deleted. Re-scan the card in ManaBox and ingest again. |
| A22 | Staleness between explicit refreshes is acceptable: legality, the Game Changer flag and edhrec_rank drift only until the owner runs `cards refresh`. | Card data, analyzer | Accepted by the owner, 2026-09-14 | A table built under stale legality, such as a card banned after the last refresh passing the analyzer. Run `cards refresh` before composing when online. |
| A23 | Bracket criteria are expressible as caps on categories, a maximum count per named card set; chaining and looping of extra turns or combos are judgment, not rules. | Analyzer | Decided in #4 (ADR-0010) against the WotC bracket definitions as read 2026-09-14 | A WotC criterion no count can express. Then the rules file grows a predicate kind, a code change. |
| A24 | Scryfall's `color_identity` is the game's colour identity for every card: both faces, hybrid and Phyrexian symbols, mana symbols in rules text. | Analyzer | Verified on one card, Wick, the Whorled Mind: `color_identity` B, R, U while `colors` is B | A colour identity dispute at the table traced to the field. Then the analyzer computes it from faces and costs itself. |
| A25 | Pattern detection generalizes to cards nobody here has seen well enough that a friend's deck gets useful metrics and bracket caps. | Analyzer | Decided in #4 (ADR-0011); unmeasured until the first external deck | Per-card corrections needed after every external deck. Then the patterns are the problem, not the lists. |
| A26 | A request has one set of themes per table; every deck at the table is measured against the same themes. | Analyzer, composer | Confirmed by the owner, 2026-09-14 | A request asking for a different theme per deck. Then `--theme` moves into the deck file or gets a per-deck form. |
| A27 | The owner bumps the rules file's `version` on every edit. | Analyzer, table store | Owner practice; `rules_hash` is the backstop | Verify (#6) reporting a changed hash under an unchanged version. |

## Invalidated

Assumptions that stopped holding, kept so nobody re-derives them.

| ID | Assumption | Replaced by | When |
|---|---|---|---|
| X1 | The tool makes no cards-to-buy recommendations. | No price awareness and no shopping lists. Unowned upgrades are in scope as the maybeboard. | #1, 2026-09-14 |
| X2 | Tables must be disjoint from each other. | Tables are independent selections; disjointness holds within a table. One table is built at a time. | #1, 2026-09-14 |
| X3 | The Scryfall layout alone decides whether an object can be a deck candidate (was A21). | An object is a token when its layout is a token layout or its printing's `set_type` is `token` (ADR-0008). Fell on the first real catalog build: the Role token "Monster // Sorcerer" from the Wilds of Eldraine token set has layout `flip`, and dungeons have layout `normal`. | #3 implementation, 2026-09-14 |

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

Source: Scryfall, checked live during the card data interview (issue #3), 2026-09-14.

| Fact | Value |
|---|---|
| transform layout (Desperate Farmer // Depraved Harvester) | no top-level `mana_cost`, `colors` or `oracle_text`; each face carries its own. Top-level `type_line` is both faces joined by ` // `, `cmc` and `color_identity` are top-level |
| prepare layout (Honorbound Page // Forum's Favor, SOS, released 2026-04-24) | top-level `mana_cost` `{3}{W} // {W}` and `colors`, no top-level `oracle_text`; faces carry text. A layout that did not exist a year earlier |
| token (Splash Lasher, TBLB) | `layout` token, `set_type` token, `legalities.commander` not_legal, `all_parts` links back to the card that makes it. Same name as the card Splash Lasher, different oracle_id |
| Wick, the Whorled Mind | `all_parts` names its Snail token with component `token`; `color_identity` B, R, U while `colors` is B |
| `GET /cards/named?exact=` | case-insensitive; a single face name resolves to the full double name |
| `POST /cards/collection` | accepts `id` and `name` identifiers mixed, up to 75 per request; returns `not_found` per identifier; a `name` identifier resolves a face name to the full name |
| Bulk files, compressed | oracle_cards 24.6 MB, default_cards 78.2 MB, all_cards 392.9 MB, refreshed daily |
| `game_changer` | present on cards and tokens as a boolean; `edhrec_rank` absent on tokens and on some cards |

Source: the committed catalog (581 cards, 46 tokens) and collection, profiled during the deck analyzer interview (issue #4), 2026-09-14.

| Fact | Value |
|---|---|
| Token lots sharing a card's name | 8, all from TBLB: Bushy Bodyguard, Coruscation Mage, Darkstar Augur, Flowerfoot Swordmaster (2 lots), Manifold Mouse, Splash Lasher, Starscape Cleric. Splash Lasher is 3 by name and 1 as a card; `owned_by_name` counts the token lots, the view does not |
| Legendary creatures among owned cards | 24; legendary non-creatures 4 (Mask of Griselbrand, Nykthos, Shrine to Nyx, Professor Dellian Fel, Ral, Crackling Wit); no owned card says "can be your commander"; no partner |
| Extra-turn cards, mass land denial | 0 and 0 |
| "Search your library" cards | 11, most fetching lands (Fabled Passage, Nervous Gardener, Shared Roots, ...) |
| Rough pattern counts, owned nonland cards | draw 102, removal 75, ramp 33 |
| Cards stating their own deck limit ("any number of cards named") | 0 |
| Basic land colour identity | each basic carries its colour: Forest G, Island U, Mountain R, Plains W, Swamp B |
| Multi-face `type_line` | faces joined by ` // `: prepare 19, class 9, transform 5, case 1 among owned cards |
| Owned cards without `edhrec_rank` | 7: the five basics, Plant a Sapling // Fully-Grown Treefolk, Prophet of Kruphix |
| The ManaBox deck "Wick, the Whorled Mind" | 70 rows, 70 cards, its commander among them; Wick's colour identity B, R, U |
| Test fixture `manabox_base.csv` | 25 rows, 24 names, 40 cards, 1 legendary, Forest 15, Plains 1: cannot hold a legal deck |
