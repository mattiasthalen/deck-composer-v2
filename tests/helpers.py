"""Test helpers: CSV rows in and out, column edits, the CLI runner, the fake
Scryfall transport."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from deck_composer import cli

FIXTURES = Path(__file__).parent / "fixtures"
BASE = FIXTURES / "manabox_base.csv"
GOLDEN = FIXTURES / "golden" / "manabox_base.collection.json"
SCRYFALL_FIXTURE = FIXTURES / "scryfall" / "manabox_base.json"

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


def load_scryfall_fixture() -> list[dict[str, Any]]:
    """The scrubbed collection-endpoint response's ``data``: 25 printings and
    their related tokens (WP0)."""
    body = json.loads(SCRYFALL_FIXTURE.read_text(encoding="utf-8"))
    return list(body["data"])


class FakeTransport:
    """A Scryfall transport served entirely from fixture objects, for tests that
    never reach the network. Callable as ``transport(method, url, headers,
    body) -> (status, bytes)``.

    ``fuzzy`` maps an input name to the object ``/cards/named?fuzzy=`` should
    answer with; an unmapped name answers 404. ``fail_with``, when set, is
    raised on every call. ``status``, when set, is returned on every call with
    an empty JSON body, taking priority over the normal responses.
    """

    def __init__(
        self,
        fixture_objects: list[dict[str, Any]],
        *,
        fuzzy: dict[str, dict[str, Any]] | None = None,
        fail_with: Exception | None = None,
        status: int | None = None,
    ) -> None:
        self.fixture_objects = list(fixture_objects)
        self.fuzzy = dict(fuzzy) if fuzzy else {}
        self.fail_with = fail_with
        self.status = status
        self.calls: list[tuple[str, str, dict[str, str], bytes]] = []

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes
    ) -> tuple[int, bytes]:
        self.calls.append((method, url, dict(headers), body))
        if self.fail_with is not None:
            raise self.fail_with
        if self.status is not None:
            return self.status, b"{}"
        if method == "POST" and url.rstrip("/").endswith("/cards/collection"):
            return self._collection_response(body)
        if method == "GET" and "/cards/named" in url and "fuzzy=" in url:
            return self._fuzzy_response(url)
        raise AssertionError(f"FakeTransport: unexpected request {method} {url}")

    def _collection_response(self, body: bytes) -> tuple[int, bytes]:
        payload = json.loads(body.decode("utf-8"))
        data: list[dict[str, Any]] = []
        not_found: list[dict[str, str]] = []
        for identifier in payload["identifiers"]:
            match = self._match(identifier)
            if match is not None:
                data.append(match)
            else:
                not_found.append(identifier)
        response = {"object": "list", "data": data, "not_found": not_found}
        return 200, json.dumps(response).encode("utf-8")

    def _match(self, identifier: dict[str, str]) -> dict[str, Any] | None:
        if "id" in identifier:
            for obj in self.fixture_objects:
                if obj.get("id") == identifier["id"]:
                    return obj
            return None
        if "name" in identifier:
            target = identifier["name"].casefold()
            for obj in self.fixture_objects:
                if obj.get("name", "").casefold() == target:
                    return obj
                for face in obj.get("card_faces") or []:
                    if face.get("name", "").casefold() == target:
                        return obj
            return None
        return None

    def _fuzzy_response(self, url: str) -> tuple[int, bytes]:
        name = parse_qs(urlparse(url).query).get("fuzzy", [""])[0]
        matched = self.fuzzy.get(name)
        if matched is None:
            return 404, json.dumps({"object": "error", "status": 404}).encode("utf-8")
        return 200, json.dumps(matched).encode("utf-8")


def recording_sleep() -> Callable[[float], None]:
    """A ``time.sleep``-shaped callable that records every duration it was
    called with, on the ``durations`` attribute, instead of sleeping."""
    durations: list[float] = []

    def sleep(seconds: float) -> None:
        durations.append(seconds)

    sleep.durations = durations  # type: ignore[attr-defined]
    return sleep
