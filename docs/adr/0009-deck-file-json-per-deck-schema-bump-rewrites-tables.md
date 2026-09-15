# ADR-0009 — The deck file is one JSON file per deck, and a schema bump rewrites every table in one commit

**Status:** Accepted (2026-09-14) · **Ticket:** [#4](https://github.com/mattiasthalen/deck-composer-v2/issues/4)

## Context

Rule 7 of the system design (#1): one canonical deck format, tools parse only it, the composer normalizes whatever a human pastes into it. The lexicon defines a deck as a list by card name and quantity with a commander and an origin. ManaBox imports a text format (assumption A11): a `// COMMANDER` section, mainboard lines, an optional `// MAYBEBOARD` section, each line `N Name`. Three tickets consume the format: the table store (#6) stores it, artifacts (#7) render the decklist from it, deck origins (#8) normalizes pasted lists into it.

ADR-0002 fixed the convention for committed data files, integer `schema`, fail loudly on an unknown value, regenerate rather than migrate, and said it applies to tables. A deck file is authored, not derived from a re-obtainable source, and accepted tables are immutable (#1), so nothing regenerates one. Names in tools are exact Scryfall names (ADR-0007); the catalog's exact lookup is `catalog.card(name)`.

## Decision

**One JSON file per deck under the ADR-0002 convention.** Fields: `schema`, `commander` as a list of exact names, `origin` from the closed set built, owned, external, `mainboard` and `maybeboard` as `{name, qty}` entries. `deck.write` renders it sorted, one entry per line, fixed key order, locked by a golden. The commander is never repeated in the mainboard; deck size is the commanders plus the mainboard quantities. Unknown keys are ignored, so an additive change needs no schema bump. Rejected: the ManaBox text as the canonical format. It has no slot for a schema, an origin, or a commander beyond a comment line, and the composer already converts pasted lists, so a second text format buys nothing.

**A name the catalog lacks is a violation, not a parse failure.** A face name, a wrong case, a typo or a token name reports `unknown_card` pointing at `cards resolve`. Parse failures are reserved for shape: malformed JSON, unknown schema, missing key, wrong type, unknown origin, quantity below one, one name twice in a section. Rejected: the lenient lookup in the analyzer; ADR-0007 keeps typo judgment with the composer, and the file is well-formed.

**A schema bump rewrites every table in the repository in one commit; main always holds the current schema.** Contents are unchanged, the analyzer proves it by parsing old and new to the same deck, and git history is the archive. Accepted freezes a deck's contents, not its bytes. Card identity across a rewrite, and across a Scryfall rename, is oracle_id. The reader accepts exactly one schema and fails loudly on any other; no migration code lives in the tree. Rejected: a table directory per version, which doubles directories and reopens "which one is current"; a multi-version reader, which is migration code under another name; the rendered decklist as the regeneration source, which external decks do not have.

**`deck.py` owns the format**, read and write, and checks shape only, never rules; a draft is allowed to be illegal. The composer may write the JSON by hand; `analyze` names the offending entry on the next run.

## Consequences

- The table store stores deck files as they are, rewrites them only through `deck.write`, and can prove a rewrite preserved a deck by oracle_id.
- Artifacts render ManaBox text from the file and drop origin and schema, which the decklist never carried.
- A breaking format change touches every table in one commit, the cost of authored files under a no-migration rule.
- Origin sits in the deck file and in table metadata; the file is authoritative for the deck, the metadata for the table.
- Partner commanders are a rule change over the list, not a format change (A14).
