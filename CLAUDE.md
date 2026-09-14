# deck-composer-v2

Deterministic Python tools behind the deck composer, a Claude Code skill that
composes Commander **tables** from a ManaBox export of the owner's physical
collection. The system design, its rules and its decomposition live in issue
#1; each module has a child ticket with its own design interview. Read the
ticket before touching a module.

## Commands

```sh
uv sync                                   # once; installs dev tools too
uv run deck-composer ingest exports/ManaBox_Collection.csv
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run pyright
```

## Tool contract (ADR-0001)

- One CLI, `deck-composer`, one subcommand per module, registered in `cli.py`.
- Success: exactly one JSON object on stdout, exit 0, always with a `next`
  sentence. Contract failure: one JSON object on stderr,
  `{"error", "detail", "next"}`, exit 1, nothing on stdout. Usage error: exit 2.
- Raise `ToolError(error, detail, next_step)` from `deck_composer.errors`; the
  CLI renders it. Every failure says what to do next. Never echo a price.
- Default paths are relative to the project root, the nearest ancestor holding
  `pyproject.toml`. The tool runs inside the repository only.
- Committed data files are JSON with an integer `schema`; readers fail loudly on
  an unknown value; there is no migration code, the data is regenerated
  (ADR-0002).

## Data layout

| Path | What | Committed |
|---|---|---|
| `exports/` | ManaBox exports (carry prices) | never |
| `data/collection.json` | the **collection**: lots from the last export, hashed by its bytes | yes |
| `tests/fixtures/` | rows cut from the real export, prices blanked; goldens | yes |

## Module ownership

| Module | Owns exclusively |
|---|---|
| `ingest.py` | The ManaBox export format: required columns, row validation, normalization |
| `collection.py` | The collection file: schema, read, write, diff by **lot key**, sum by name |
| `cli.py` | Argument parsing, JSON rendering, exit codes, project root |

A module never parses another module's format. Card data (#3) and the table
store (#6) read the collection through `collection.read`.

## Vocabulary

Use the words in `docs/lexicon.md` and only those, in code identifiers, tests,
tickets and docs. A term the lexicon defines has exactly that meaning here.
Assumptions the design relies on, with what would falsify each, are in
`docs/design/assumptions.md`. Decisions are in `docs/adr/`.

## Fixture policy

Fixtures are real rows from the owner's export with `Purchase price` blanked.
Never commit an export. Never put a non-empty price in a fixture. The golden
`tests/fixtures/golden/*.collection.json` locks the collection file layout; a
deliberate layout change regenerates it, nothing else does.

## Testing

Unit tests with fixtures; a byte-exact golden for the collection file;
determinism (same export, same bytes); every failure class; the change report.
Tests call functions directly and the CLI through `main()`.
