# ADR-0002 — The collection is one sorted JSON file with an integer schema, regenerated rather than migrated

**Status:** Accepted (2026-09-14) · **Superseded in part:** the consequence that per-card ownership calls sum by name, by [ADR-0013](0013-ownership-per-card-joins-through-printings.md) (2026-09-14) · **Ticket:** [#2](https://github.com/mattiasthalen/deck-composer-v2/issues/2)

## Context

Rule 3 of the system design (#1): files in git are the source of truth, no database service. The collection is the normalized ownership record derived from one ManaBox export and is authoritative for ownership. Card data (#3) and the table store (#6) read it; the composer never reads it directly. The raw export is not committed because it carries purchase prices.

Measured on 2026-09-14: 869 lots, 1,354 physical cards, 603 names, 676 printings. The design target is ten times that (A7). Git diff is the review tool for every change to committed data. The export can be produced again from ManaBox at any time.

## Decision

**One file, `data/collection.json`, valid JSON, one lot per line, lots sorted deterministically.** The same export bytes give byte-identical output. Rejected: CSV with a sidecar metadata file, two files that must stay in step and a stringly typed record; JSONL with a leading metadata record, a special first line every reader must treat differently; pretty-printed JSON, which spreads a lot over a dozen lines and makes diffs unreadable.

**An integer `schema` field; readers fail loudly on an unknown value; no migration code.** A schema bump is handled by re-exporting from ManaBox and running ingest again. Ingest itself tolerates an unreadable previous file, since it is the tool that produces the current schema. Rejected: migration code from one schema to the next. The source is re-obtainable, so a migration would be code written once per bump and run once. The convention applies to every committed data file the project adds (catalog, tables).

**`collection_hash` is `sha256:` of the raw export bytes.** It identifies the ownership snapshot independent of the collection file's format, so a schema bump under the same export keeps the hash, and tables that recorded it still match. Hashing the collection file instead would change with every format change and duplicates what git's blob hash already provides.

**A `collection` module owns the file format**: schema, read, write, diff by lot key and sum by name. Ingest owns the ManaBox export format and nothing else. Rejected: keeping the format inside ingest. Consumers would import from a ManaBox-named module, and a ManaBox format change would touch the module every other module depends on.

## Consequences

- Readers need one JSON load and one import. Git diff shows changes lot by lot, ordered by card name.
- The writer is custom rather than `json.dump`, and its exact layout is locked by a byte-exact golden test. A layout change regenerates the golden.
- A schema bump forces a re-export. The new export may differ from the old, so the collection may change contents at the same moment its format does; verify (#6) reports the difference against accepted tables.
- At ten times today's size the file is a few megabytes and still one document; there is no partial or streaming read.
- Consumers that need lot-level data (binder scoping) read lots; consumers that need per-card ownership call sum by name. Neither parses the file itself.
