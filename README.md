# deck-composer-v2

Compose Commander tables from a ManaBox export of a physical collection. The
composer is a Claude Code skill; this repository holds the deterministic Python
tools it calls and the committed data they produce. Design: issue #1 and its
children; decisions in `docs/adr/`; vocabulary in `docs/lexicon.md`.

```sh
uv sync
uv run deck-composer ingest exports/ManaBox_Collection.csv
uv run pytest
```
