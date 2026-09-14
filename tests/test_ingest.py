"""Ingest: the base fixture against its golden, every failure class, the change report."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from deck_composer import ingest as ingest_module
from deck_composer.collection import read
from deck_composer.errors import ToolError
from deck_composer.ingest import ingest
from tests.helpers import (
    BASE,
    GOLDEN,
    Header,
    Rows,
    drop_columns,
    find_row,
    get_value,
    render,
    run_cli,
    set_value,
    write_export,
)


def ingest_rows(tmp_path: Path, header: Header, rows: Rows, **render_options: object) -> dict:
    export = write_export(tmp_path / "export.csv", header, rows, **render_options)
    return ingest(export, tmp_path / "out.json").to_dict()


def failure(tmp_path: Path, header: Header, rows: Rows, **render_options: object) -> ToolError:
    export = write_export(tmp_path / "export.csv", header, rows, **render_options)
    with pytest.raises(ToolError) as caught:
        ingest(export, tmp_path / "out.json")
    assert not (tmp_path / "out.json").exists()
    return caught.value


# --- happy path -------------------------------------------------------------


def test_base_fixture_matches_golden_byte_for_byte(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    result = ingest(BASE, out).to_dict()
    assert out.read_bytes() == GOLDEN.read_bytes()
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["schema"] == 1
    assert len(body["lots"]) == 25 == body["source"]["rows"] == result["lots"]
    assert body["source"]["file"] == "manabox_base.csv"


def test_reingest_is_byte_identical_and_reports_nothing_changed(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    ingest(BASE, out)
    first = out.read_bytes()
    result = ingest(BASE, out).to_dict()
    assert out.read_bytes() == first
    changes = result["changes"]
    assert changes["lots"] == {"added": 0, "removed": 0, "quantity_changed": 0}
    assert changes["cards_delta"] == 0
    assert changes["names"] == {"added": [], "removed": [], "quantity_changed": []}
    assert result["previous_collection"] == result["collection_hash"]
    assert result["next"].startswith("Nothing changed")


def test_collection_hash_is_sha256_of_the_export_bytes(
    tmp_path: Path, base: tuple[Header, Rows]
) -> None:
    result = ingest(BASE, tmp_path / "out.json").to_dict()
    assert result["collection_hash"] == "sha256:" + hashlib.sha256(BASE.read_bytes()).hexdigest()
    header, rows = base
    set_value(header, rows[0], "Added", "2030-01-01T00:00:00.000Z")
    changed = ingest_rows(tmp_path, header, rows)
    assert changed["collection_hash"] != result["collection_hash"]


def test_set_codes_are_lowercased(tmp_path: Path, base: tuple[Header, Rows]) -> None:
    header, rows = base
    assert any(get_value(header, row, "Set code").isupper() for row in rows)
    ingest(BASE, tmp_path / "out.json")
    lots = read(tmp_path / "out.json").lots
    assert all(lot.set_code == lot.set_code.lower() for lot in lots)
    assert {lot.set_code for lot in lots} >= {"blb", "ths", "tblb", "fdn"}


def test_lots_are_sorted(tmp_path: Path) -> None:
    ingest(BASE, tmp_path / "out.json")
    lots = json.loads((tmp_path / "out.json").read_text())["lots"]
    keys = [
        (
            lot["name"],
            lot["set_code"],
            lot["collector_number"],
            lot["foil"],
            lot["condition"],
            lot["language"],
            lot["binder_name"],
            lot["binder_type"],
            lot["added"] is None,
            lot["added"] or "",
        )
        for lot in lots
    ]
    assert keys == sorted(keys)


def test_names_with_slashes_and_commas_are_verbatim(tmp_path: Path) -> None:
    ingest(BASE, tmp_path / "out.json")
    names = {lot.name for lot in read(tmp_path / "out.json").lots}
    assert {"Desperate Farmer // Depraved Harvester", "Wick, the Whorled Mind"} <= names


def test_quantity_is_an_integer_and_cards_is_their_sum(tmp_path: Path) -> None:
    result = ingest(BASE, tmp_path / "out.json").to_dict()
    lots = read(tmp_path / "out.json").lots
    forest = next(lot for lot in lots if lot.name == "Forest")
    assert forest.quantity == 15 and isinstance(forest.quantity, int)
    assert result["cards"] == sum(lot.quantity for lot in lots) == 40


def test_ignored_columns_in_header_order_and_prices_never_leak(
    tmp_path: Path, base: tuple[Header, Rows]
) -> None:
    header, rows = base
    for row in rows:
        set_value(header, row, "Purchase price", "1234.56")
    result = ingest_rows(tmp_path, header, rows)
    assert result["ignored_columns"] == [
        "Set name",
        "Rarity",
        "ManaBox ID",
        "Purchase price",
        "Misprint",
        "Altered",
        "Purchase price currency",
    ]
    assert "1234.56" not in (tmp_path / "out.json").read_text()
    assert "1234.56" not in json.dumps(result)


def test_failure_output_never_carries_a_price(tmp_path: Path, base: tuple[Header, Rows]) -> None:
    header, rows = base
    for row in rows:
        set_value(header, row, "Purchase price", "1234.56")
    set_value(header, rows[3], "Quantity", "zero")
    error = failure(tmp_path, header, rows)
    assert "1234.56" not in json.dumps(error.to_dict())


def test_added_is_verbatim_and_latest_added_is_the_maximum(tmp_path: Path) -> None:
    result = ingest(BASE, tmp_path / "out.json").to_dict()
    lots = read(tmp_path / "out.json").lots
    added = [lot.added for lot in lots if lot.added is not None]
    assert len(added) == len(lots)
    assert all(value.endswith("Z") for value in added)
    assert result["latest_added"] == max(added) == "2026-08-26T17:14:46.333Z"


def test_missing_added_column_gives_nulls(tmp_path: Path, base: tuple[Header, Rows]) -> None:
    header, rows = drop_columns(*base, "Added")
    result = ingest_rows(tmp_path, header, rows)
    assert result["latest_added"] is None
    assert all(lot.added is None for lot in read(tmp_path / "out.json").lots)


def test_empty_added_value_is_null(tmp_path: Path, base: tuple[Header, Rows]) -> None:
    header, rows = base
    set_value(header, rows[0], "Added", "")
    ingest_rows(tmp_path, header, rows)
    lots = read(tmp_path / "out.json").lots
    assert sum(1 for lot in lots if lot.added is None) == 1


def test_binders_summary(tmp_path: Path, base: tuple[Header, Rows]) -> None:
    header, rows = base
    set_value(header, rows[0], "Binder Name", "Second")
    set_value(header, rows[0], "Binder Type", "deck")
    result = ingest_rows(tmp_path, header, rows)
    assert result["binders"] == [
        {"name": "OmniHive: Secrets of Strixhaven", "type": "binder", "lots": 24},
        {"name": "Second", "type": "deck", "lots": 1},
    ]
    assert sum(binder["lots"] for binder in result["binders"]) == result["lots"]
    assert any(lot.binder_type == "deck" for lot in read(tmp_path / "out.json").lots)


def test_bom_and_crlf_change_the_hash_but_not_the_lots(
    tmp_path: Path, base: tuple[Header, Rows]
) -> None:
    header, rows = base
    export = write_export(tmp_path / "export.csv", header, rows, newline="\r\n", bom=True)
    assert export.read_bytes().startswith(b"\xef\xbb\xbf") and b"\r\n" in export.read_bytes()
    result = ingest(export, tmp_path / "out.json").to_dict()
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert json.loads((tmp_path / "out.json").read_text())["lots"] == golden["lots"]
    assert result["collection_hash"] != golden["collection_hash"]


def test_file_is_lf_terminated_and_keeps_non_ascii(
    tmp_path: Path, base: tuple[Header, Rows]
) -> None:
    header, rows = base
    set_value(header, rows[0], "Name", "Lim-Dûl's Vault")
    ingest_rows(tmp_path, header, rows)
    text = (tmp_path / "out.json").read_bytes().decode("utf-8")
    assert "\r" not in text and text.endswith("\n")
    assert "Lim-Dûl's Vault" in text and "\\u00fb" not in text


def test_summary_counts(tmp_path: Path) -> None:
    result = ingest(BASE, tmp_path / "out.json").to_dict()
    assert result["names"] == 24
    assert result["printings"] == 25
    assert result["previous_collection"] == "none"
    assert result["changes"] is None


# --- failures ---------------------------------------------------------------


def test_missing_one_required_column(tmp_path: Path, base: tuple[Header, Rows]) -> None:
    error = failure(tmp_path, *drop_columns(*base, "Scryfall ID"))
    assert error.error == "missing_columns"
    assert error.detail["missing"] == ["Scryfall ID"]


def test_missing_three_required_columns(tmp_path: Path, base: tuple[Header, Rows]) -> None:
    error = failure(tmp_path, *drop_columns(*base, "Foil", "Condition", "Language"))
    assert error.detail["missing"] == ["Foil", "Condition", "Language"]


def test_semicolon_delimiter_reads_as_one_odd_column(
    tmp_path: Path, base: tuple[Header, Rows]
) -> None:
    error = failure(tmp_path, *base, delimiter=";")
    assert error.error == "missing_columns"
    assert error.detail["missing"] == list(ingest_module.REQUIRED_COLUMNS)
    assert len(error.detail["found"]) == 1


def test_duplicate_header(tmp_path: Path, base: tuple[Header, Rows]) -> None:
    header, rows = base
    header = [*header, "Name"]
    rows = [[*row, "extra"] for row in rows]
    error = failure(tmp_path, header, rows)
    assert error.error == "duplicate_columns"
    assert error.detail["duplicated"] == ["Name"]


def test_header_only(tmp_path: Path, base: tuple[Header, Rows]) -> None:
    header, _ = base
    error = failure(tmp_path, header, [])
    assert error.error == "no_rows"


def test_empty_file(tmp_path: Path) -> None:
    export = tmp_path / "export.csv"
    export.write_bytes(b"")
    with pytest.raises(ToolError) as caught:
        ingest(export, tmp_path / "out.json")
    assert caught.value.error == "missing_columns"
    assert caught.value.detail["found"] == []


def test_not_utf8(tmp_path: Path) -> None:
    export = tmp_path / "export.csv"
    export.write_bytes(b"Name,Quantity\r\n\xff\xfe\x00bad\r\n")
    with pytest.raises(ToolError) as caught:
        ingest(export, tmp_path / "out.json")
    assert caught.value.error == "export_not_utf8"
    assert caught.value.detail["byte_offset"] == 15


@pytest.mark.parametrize("quantity", ["0", "-1", "1.5", ""])
def test_bad_quantities(tmp_path: Path, base: tuple[Header, Rows], quantity: str) -> None:
    header, rows = base
    set_value(header, rows[4], "Quantity", quantity)
    error = failure(tmp_path, header, rows)
    assert error.error == "invalid_rows"
    assert error.detail["total"] == 1
    [row] = error.detail["rows"]
    assert row["line"] == 6
    assert row["name"] == get_value(header, rows[4], "Name")
    assert row["problems"] == ["quantity_not_positive_integer"]


@pytest.mark.parametrize("scryfall_id", ["", "not-a-uuid", "0ec488de-fded-4df9-97ed"])
def test_bad_scryfall_ids(tmp_path: Path, base: tuple[Header, Rows], scryfall_id: str) -> None:
    header, rows = base
    set_value(header, rows[0], "Scryfall ID", scryfall_id)
    error = failure(tmp_path, header, rows)
    assert error.detail["rows"][0]["problems"] == ["scryfall_id_invalid"]


def test_unknown_binder_type(tmp_path: Path, base: tuple[Header, Rows]) -> None:
    header, rows = base
    set_value(header, rows[0], "Binder Type", "list")
    error = failure(tmp_path, header, rows)
    assert error.detail["rows"][0]["problems"] == ["binder_type_unknown:list"]
    assert "BINDER_TYPES" in error.next_step


def test_empty_required_value(tmp_path: Path, base: tuple[Header, Rows]) -> None:
    header, rows = base
    set_value(header, rows[0], "Foil", "")
    error = failure(tmp_path, header, rows)
    assert error.detail["rows"][0]["problems"] == ["empty:Foil"]


def test_row_detail_is_capped_with_a_total(
    tmp_path: Path, base: tuple[Header, Rows], monkeypatch: pytest.MonkeyPatch
) -> None:
    header, rows = base
    for row in rows[:3]:
        set_value(header, row, "Quantity", "x")
    error = failure(tmp_path, header, rows)
    assert error.detail["total"] == error.detail["shown"] == 3
    monkeypatch.setattr(ingest_module, "ROW_DETAIL_CAP", 2)
    error = failure(tmp_path, header, rows)
    assert (error.detail["shown"], error.detail["total"]) == (2, 3)
    assert len(error.detail["rows"]) == 2


def test_failure_leaves_the_existing_collection_untouched(
    tmp_path: Path, base: tuple[Header, Rows]
) -> None:
    out = tmp_path / "out.json"
    ingest(BASE, out)
    before = out.read_bytes()
    header, rows = drop_columns(*base, "Name")
    export = write_export(tmp_path / "export.csv", header, rows)
    with pytest.raises(ToolError):
        ingest(export, out)
    assert out.read_bytes() == before


def test_export_not_found(tmp_path: Path) -> None:
    for path in (tmp_path / "nope.csv", tmp_path):
        with pytest.raises(ToolError) as caught:
            ingest(path, tmp_path / "out.json")
        assert caught.value.error == "export_not_found"


# --- change report ----------------------------------------------------------


def test_previous_not_json_is_reported_and_replaced(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    out.write_text("not json")
    result = ingest(BASE, out).to_dict()
    assert result["previous_collection"] == "unreadable"
    assert result["changes"] is None
    assert "could not be read" in result["next"]
    assert read(out).collection_hash == result["collection_hash"]


def test_previous_unknown_schema_is_reported_and_replaced(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    out.write_text(json.dumps({"schema": 2, "lots": []}))
    result = ingest(BASE, out).to_dict()
    assert result["previous_collection"] == "unreadable"
    assert result["changes"] is None
    assert out.read_bytes() == GOLDEN.read_bytes()


def test_removed_lots(tmp_path: Path, base: tuple[Header, Rows]) -> None:
    header, rows = base
    out = tmp_path / "out.json"
    ingest(BASE, out)
    forest = find_row(header, rows, "Forest")
    quick_study = find_row(header, rows, "Quick Study")
    rows = [row for row in rows if row is not forest and row is not quick_study]
    export = write_export(tmp_path / "export.csv", header, rows)
    changes = ingest(export, out).to_dict()["changes"]
    assert changes["lots"] == {"added": 0, "removed": 2, "quantity_changed": 0}
    assert changes["cards_delta"] == -16
    assert changes["names"]["removed"] == ["Forest"]
    assert changes["names"]["quantity_changed"] == [{"name": "Quick Study", "from": 2, "to": 1}]


def test_added_lot_with_a_new_name(tmp_path: Path, base: tuple[Header, Rows]) -> None:
    header, rows = base
    out = tmp_path / "out.json"
    ingest(BASE, out)
    new = list(rows[0])
    set_value(header, new, "Name", "Brand New Card")
    set_value(header, new, "Scryfall ID", "00000000-0000-4000-8000-000000000001")
    export = write_export(tmp_path / "export.csv", header, [*rows, new])
    changes = ingest(export, out).to_dict()["changes"]
    assert changes["lots"] == {"added": 1, "removed": 0, "quantity_changed": 0}
    assert changes["names"]["added"] == ["Brand New Card"]
    assert changes["cards_delta"] == 1


def test_quantity_change(tmp_path: Path, base: tuple[Header, Rows]) -> None:
    header, rows = base
    out = tmp_path / "out.json"
    ingest(BASE, out)
    set_value(header, find_row(header, rows, "Seedpod Squire"), "Quantity", "3")
    export = write_export(tmp_path / "export.csv", header, rows)
    changes = ingest(export, out).to_dict()["changes"]
    assert changes["lots"] == {"added": 0, "removed": 0, "quantity_changed": 1}
    assert changes["names"]["quantity_changed"] == [{"name": "Seedpod Squire", "from": 2, "to": 3}]
    assert changes["cards_delta"] == 1
    assert changes["previous_hash"] == json.loads(GOLDEN.read_text())["collection_hash"]


def test_binder_move_is_a_removal_and_an_addition(
    tmp_path: Path, base: tuple[Header, Rows]
) -> None:
    header, rows = base
    out = tmp_path / "out.json"
    ingest(BASE, out)
    set_value(header, find_row(header, rows, "Forest"), "Binder Name", "Elsewhere")
    export = write_export(tmp_path / "export.csv", header, rows)
    changes = ingest(export, out).to_dict()["changes"]
    assert changes["lots"] == {"added": 1, "removed": 1, "quantity_changed": 0}
    assert changes["names"] == {"added": [], "removed": [], "quantity_changed": []}
    assert changes["cards_delta"] == 0


def test_only_added_changed_is_no_ownership_change(
    tmp_path: Path, base: tuple[Header, Rows]
) -> None:
    header, rows = base
    out = tmp_path / "out.json"
    ingest(BASE, out)
    for row in rows:
        set_value(header, row, "Added", "2030-01-01T00:00:00.000Z")
    export = write_export(tmp_path / "export.csv", header, rows)
    result = ingest(export, out).to_dict()
    assert result["changes"]["lots"] == {"added": 0, "removed": 0, "quantity_changed": 0}
    assert result["changes"]["names"] == {"added": [], "removed": [], "quantity_changed": []}
    assert result["next"].startswith("No ownership changes")


def test_duplicate_lot_keys_are_kept_and_summed_for_the_report(
    tmp_path: Path, base: tuple[Header, Rows]
) -> None:
    header, rows = base
    out = tmp_path / "out.json"
    forest = find_row(header, rows, "Forest")
    set_value(header, forest, "Quantity", "3")
    ingest(write_export(tmp_path / "before.csv", header, rows), out)
    twin = list(forest)
    set_value(header, forest, "Quantity", "1")
    set_value(header, twin, "Quantity", "2")
    set_value(header, twin, "Added", "2026-08-30T00:00:00.000Z")
    export = write_export(tmp_path / "after.csv", header, [*rows, twin])
    result = ingest(export, out).to_dict()
    assert result["changes"]["lots"] == {"added": 0, "removed": 0, "quantity_changed": 0}
    assert result["lots"] == 26
    assert sum(lot.quantity for lot in read(out).lots if lot.name == "Forest") == 3


def test_cli_reports_the_change_report(
    capsys: pytest.CaptureFixture[str], repo: Path, base: tuple[Header, Rows]
) -> None:
    header, rows = base
    run_cli(capsys, "ingest", str(BASE))
    set_value(header, find_row(header, rows, "Forest"), "Quantity", "20")
    export = write_export(repo / "export.csv", header, rows)
    result = run_cli(capsys, "ingest", str(export))
    assert result.code == 0
    assert result.out_json["changes"]["cards_delta"] == 5
    assert result.out_json["next"] == "Review changes, then commit data/collection.json."
    assert render(header, rows) == export.read_text(encoding="utf-8")
