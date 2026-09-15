"""Tool contract (ADR-0001): exit codes, one JSON object per stream, project root."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import pytest

from deck_composer import cli
from deck_composer.scryfall import Client
from tests.helpers import (
    BASE,
    FIXTURES,
    GOLDEN,
    FakeTransport,
    load_scryfall_fixture,
    recording_sleep,
    run_cli,
)


def test_help_lists_ingest(capsys: pytest.CaptureFixture[str]) -> None:
    result = run_cli(capsys, "--help")
    assert result.code == 0
    assert "ingest" in result.out


@pytest.mark.parametrize("argv", [(), ("frobnicate",), ("ingest",)])
def test_usage_errors_exit_2(capsys: pytest.CaptureFixture[str], argv: tuple[str, ...]) -> None:
    result = run_cli(capsys, *argv)
    assert result.code == 2
    assert result.err
    assert result.out == ""


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    result = run_cli(capsys, "--version")
    assert result.code == 0
    assert result.out.strip() == f"deck-composer {version('deck-composer')}"


def test_success_is_one_json_object_with_next(
    capsys: pytest.CaptureFixture[str], repo: Path
) -> None:
    result = run_cli(capsys, "ingest", str(BASE))
    assert result.code == 0
    assert result.err == ""
    body = result.out_json
    assert isinstance(body["next"], str) and body["next"]
    assert body["collection"] == "data/collection.json"
    assert body["collection"] in body["next"]
    assert (repo / "data" / "collection.json").is_file()


def test_failure_is_one_json_object_on_stderr(
    capsys: pytest.CaptureFixture[str], repo: Path
) -> None:
    result = run_cli(capsys, "ingest", str(repo / "missing.csv"))
    assert result.code == 1
    assert result.out == ""
    body = result.err_json
    assert body["error"] == "export_not_found"
    assert isinstance(body["detail"], dict)
    assert body["next"]


def test_project_root_not_found(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = run_cli(capsys, "ingest", str(BASE))
    assert result.code == 1
    assert result.err_json["error"] == "project_root_not_found"


def test_default_output_is_under_root_from_a_subdirectory(
    capsys: pytest.CaptureFixture[str], repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = repo / "somewhere" / "deep"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    result = run_cli(capsys, "ingest", str(BASE))
    assert result.code == 0
    assert (repo / "data" / "collection.json").is_file()
    assert result.out_json["collection"] == "data/collection.json"


# --- cards: the three operations, offline against a catalog that already covers -


CATALOG_GOLDEN = FIXTURES / "golden" / "manabox_base.catalog.json"


@pytest.fixture
def covered(repo: Path) -> Path:
    """A project root whose committed catalog already covers its collection, so
    every operation the CLI runs here makes no request."""
    data = repo / "data"
    data.mkdir()
    (data / "collection.json").write_bytes(GOLDEN.read_bytes())
    (data / "catalog.json").write_bytes(CATALOG_GOLDEN.read_bytes())
    return repo


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """The client the CLI builds, served from the Scryfall fixture: an operation
    that does fetch still reaches no network."""
    monkeypatch.setattr(
        cli,
        "_client",
        lambda: Client(
            transport=FakeTransport(load_scryfall_fixture()),
            sleep=recording_sleep(),
            version="test",
        ),
    )


def test_cards_help_lists_the_three_operations(capsys: pytest.CaptureFixture[str]) -> None:
    result = run_cli(capsys, "cards", "--help")
    assert result.code == 0
    for operation in ("enrich", "refresh", "resolve"):
        assert operation in result.out


@pytest.mark.parametrize("argv", [("cards",), ("cards", "frobnicate"), ("cards", "resolve")])
def test_cards_usage_errors_exit_2(
    capsys: pytest.CaptureFixture[str], covered: Path, argv: tuple[str, ...]
) -> None:
    result = run_cli(capsys, *argv)
    assert result.code == 2
    assert result.err
    assert result.out == ""


def test_cards_enrich_succeeds_offline_and_reports_both_paths(
    capsys: pytest.CaptureFixture[str], covered: Path
) -> None:
    result = run_cli(capsys, "cards", "enrich")
    assert result.code == 0
    assert result.err == ""
    body = result.out_json
    assert body["catalog"] == "data/catalog.json"
    assert body["view"] == "data/collection_view.tsv"
    assert body["fetched"] == {"printings": 0, "tokens": 0, "requests": 0}
    assert body["catalog_written"] is False
    assert isinstance(body["next"], str) and body["next"]
    assert (covered / "data" / "collection_view.tsv").is_file()


def test_cards_enrich_from_a_subdirectory_writes_under_the_root(
    capsys: pytest.CaptureFixture[str], covered: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = covered / "somewhere" / "deep"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    result = run_cli(capsys, "cards", "enrich")
    assert result.code == 0
    assert result.out_json["catalog"] == "data/catalog.json"
    assert result.out_json["view"] == "data/collection_view.tsv"
    assert (covered / "data" / "collection_view.tsv").is_file()
    assert not (nested / "data").exists()


def test_cards_enrich_with_an_unknown_binder_fails_on_stderr(
    capsys: pytest.CaptureFixture[str], covered: Path
) -> None:
    result = run_cli(capsys, "cards", "enrich", "--exclude-binder", "Nope")
    assert result.code == 1
    assert result.out == ""
    body = result.err_json
    assert body["error"] == "binder_unknown"
    assert body["detail"]["unknown"] == ["Nope"]
    assert isinstance(body["next"], str) and body["next"]


def test_cards_enrich_takes_the_path_flags(
    capsys: pytest.CaptureFixture[str], covered: Path
) -> None:
    view = covered / "elsewhere" / "view.tsv"
    result = run_cli(capsys, "cards", "enrich", "--view", str(view))
    assert result.code == 0
    assert result.out_json["view"] == "elsewhere/view.tsv"
    assert view.is_file()


def test_cards_resolve_from_a_file(capsys: pytest.CaptureFixture[str], covered: Path) -> None:
    names = covered / "names.txt"
    names.write_text(
        "# a maybeboard\nWick, the Whorled Mind\n\nForest\nQuick Study\n", encoding="utf-8"
    )
    result = run_cli(capsys, "cards", "resolve", "--file", str(names))
    assert result.code == 0
    assert result.err == ""
    body = result.out_json
    assert [entry["input"] for entry in body["results"]] == [
        "Wick, the Whorled Mind",
        "Forest",
        "Quick Study",
    ]
    assert body["resolved"] == 3
    assert body["catalog_written"] is False
    assert isinstance(body["next"], str) and body["next"]


def test_cards_resolve_without_a_names_file(
    capsys: pytest.CaptureFixture[str], covered: Path
) -> None:
    result = run_cli(capsys, "cards", "resolve", "--file", str(covered / "missing.txt"))
    assert result.code == 1
    assert result.out == ""
    assert result.err_json["error"] == "names_file_unreadable"


def test_cards_resolve_with_a_file_of_only_comments_exits_2(
    capsys: pytest.CaptureFixture[str], covered: Path
) -> None:
    names = covered / "names.txt"
    names.write_text("# nothing here\n\n", encoding="utf-8")
    result = run_cli(capsys, "cards", "resolve", "--file", str(names))
    assert result.code == 2
    assert result.out == ""


def test_cards_refresh_succeeds_and_reports_the_change_report(
    capsys: pytest.CaptureFixture[str], covered: Path, offline: None
) -> None:
    result = run_cli(capsys, "cards", "refresh")
    assert result.code == 0
    assert result.err == ""
    body = result.out_json
    assert body["catalog"] == "data/catalog.json"
    assert body["view"] == "data/collection_view.tsv"
    assert body["refreshed"] == datetime.now(UTC).date().isoformat()
    assert body["catalog_written"] is True
    assert all(not body["changes"][key] for key in body["changes"])
    assert isinstance(body["next"], str) and body["next"]
    assert (covered / "data" / "collection_view.tsv").is_file()


def test_cards_refresh_without_a_catalog(capsys: pytest.CaptureFixture[str], repo: Path) -> None:
    data = repo / "data"
    data.mkdir()
    (data / "collection.json").write_bytes(GOLDEN.read_bytes())
    result = run_cli(capsys, "cards", "refresh")
    assert result.code == 1
    assert result.out == ""
    body = result.err_json
    assert body["error"] == "catalog_not_found"
    assert "enrich" in body["next"]
