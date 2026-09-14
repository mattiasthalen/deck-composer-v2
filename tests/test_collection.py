"""The collection module: read failures, sum by name, determinism, repo data hygiene."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from deck_composer.collection import Collection, Lot, owned_by_name, read, render, write
from deck_composer.errors import ToolError
from tests.helpers import FIXTURES, GOLDEN

REPO = Path(__file__).resolve().parent.parent


def lot(name: str, quantity: int, binder: str = "A", scryfall_id: str = "x") -> Lot:
    return Lot(
        name=name,
        set_code="blb",
        collector_number="1",
        scryfall_id=scryfall_id,
        quantity=quantity,
        foil="normal",
        condition="mint",
        language="en",
        binder_name=binder,
        binder_type="binder",
        added=None,
    )


def test_read_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ToolError) as caught:
        read(tmp_path / "none.json")
    assert caught.value.error == "collection_not_found"
    assert "ingest" in caught.value.next_step


def test_read_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"schema": 2, "lots": []}))
    with pytest.raises(ToolError) as caught:
        read(path)
    assert caught.value.error == "collection_schema_unknown"
    assert caught.value.detail["schema"] == 2


@pytest.mark.parametrize("text", ["", "not json", "[1, 2]", '{"schema": 1}'])
def test_read_unreadable(tmp_path: Path, text: str) -> None:
    path = tmp_path / "c.json"
    path.write_text(text)
    with pytest.raises(ToolError) as caught:
        read(path)
    assert caught.value.error in {"collection_unreadable", "collection_schema_unknown"}


def test_read_ignores_unknown_top_level_fields(tmp_path: Path) -> None:
    body = json.loads(GOLDEN.read_text(encoding="utf-8"))
    body["future_field"] = {"anything": True}
    path = tmp_path / "c.json"
    path.write_text(json.dumps(body))
    assert len(read(path).lots) == 25


def test_golden_round_trips(tmp_path: Path) -> None:
    collection = read(GOLDEN)
    write(collection, tmp_path / "again.json")
    assert (tmp_path / "again.json").read_bytes() == GOLDEN.read_bytes()


def test_owned_by_name_sums_across_lots() -> None:
    collection = Collection("sha256:0", "x.csv", (lot("Forest", 1, "A"), lot("Forest", 2, "B")))
    assert owned_by_name(collection) == {"Forest": 3}


def test_write_is_deterministic_and_sorted(tmp_path: Path) -> None:
    lots = (lot("Zebra", 1), lot("Aardvark", 1))
    first, second = (
        Collection("sha256:0", "x.csv", lots),
        Collection("sha256:0", "x.csv", lots[::-1]),
    )
    assert render(first) == render(second)
    assert [entry.name for entry in first.lots] == ["Aardvark", "Zebra"]


def test_fixtures_carry_no_prices() -> None:
    for path in FIXTURES.glob("*.csv"):
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert rows, path
        assert all(row["Purchase price"] == "" for row in rows), path


def test_committed_collection_is_price_free() -> None:
    path = REPO / "data" / "collection.json"
    if not path.exists():
        pytest.skip("no committed collection in this checkout")
    text = path.read_text(encoding="utf-8")
    assert "price" not in text.lower()
    collection = read(path)
    assert collection.lots
