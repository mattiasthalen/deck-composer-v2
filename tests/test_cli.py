"""Tool contract (ADR-0001): exit codes, one JSON object per stream, project root."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path

import pytest

from tests.helpers import BASE, run_cli


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
