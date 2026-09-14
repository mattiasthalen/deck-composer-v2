"""Test helpers: CSV rows in and out, column edits, the CLI runner."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from deck_composer import cli

FIXTURES = Path(__file__).parent / "fixtures"
BASE = FIXTURES / "manabox_base.csv"
GOLDEN = FIXTURES / "golden" / "manabox_base.collection.json"

Header = list[str]
Rows = list[list[str]]


def parse(text: str) -> tuple[Header, Rows]:
    records = list(csv.reader(io.StringIO(text, newline="")))
    return records[0], records[1:]


def render(
    header: Header, rows: Rows, *, newline: str = "\n", bom: bool = False, delimiter: str = ","
) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator=newline, delimiter=delimiter)
    writer.writerow(header)
    writer.writerows(rows)
    return ("\ufeff" if bom else "") + out.getvalue()


def write_export(path: Path, header: Header, rows: Rows, **render_options: Any) -> Path:
    path.write_bytes(render(header, rows, **render_options).encode("utf-8"))
    return path


def column(header: Header, name: str) -> int:
    return header.index(name)


def set_value(header: Header, row: list[str], name: str, value: str) -> None:
    row[column(header, name)] = value


def get_value(header: Header, row: list[str], name: str) -> str:
    return row[column(header, name)]


def drop_columns(header: Header, rows: Rows, *names: str) -> tuple[Header, Rows]:
    keep = [i for i, name in enumerate(header) if name not in names]
    return [header[i] for i in keep], [[row[i] for i in keep] for row in rows]


def find_row(header: Header, rows: Rows, name: str) -> list[str]:
    return next(row for row in rows if get_value(header, row, "Name") == name)


@dataclass
class CliResult:
    code: int | str | None
    out: str
    err: str

    @property
    def out_json(self) -> dict[str, Any]:
        return json.loads(self.out)

    @property
    def err_json(self) -> dict[str, Any]:
        return json.loads(self.err)


def run_cli(capsys: pytest.CaptureFixture[str], *argv: str) -> CliResult:
    try:
        code: int | str | None = cli.main(list(argv))
    except SystemExit as exit_:
        code = exit_.code
    captured = capsys.readouterr()
    return CliResult(code, captured.out, captured.err)
