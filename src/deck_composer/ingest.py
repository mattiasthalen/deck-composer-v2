"""ManaBox export in, collection out. Owns the export format and nothing else.

Requires the columns it uses, ignores extras, fails loudly on drift (rule 6
of #1). Reads the whole file, then reports every problem of one class at once.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deck_composer.collection import (
    BINDER_TYPES,
    HASH_PREFIX,
    ChangeReport,
    Collection,
    Lot,
    diff,
    read,
    write,
)
from deck_composer.errors import ToolError

REQUIRED_COLUMNS: tuple[str, ...] = (
    "Binder Name",
    "Binder Type",
    "Name",
    "Set code",
    "Collector number",
    "Foil",
    "Quantity",
    "Scryfall ID",
    "Condition",
    "Language",
)
OPTIONAL_COLUMNS: tuple[str, ...] = ("Added",)
# Required columns whose only check is "non-empty". Quantity and Scryfall ID have their own.
_TEXT_COLUMNS: tuple[str, ...] = (
    "Binder Name",
    "Binder Type",
    "Name",
    "Set code",
    "Collector number",
    "Foil",
    "Condition",
    "Language",
)
ROW_DETAIL_CAP = 25

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_QUANTITY = re.compile(r"[0-9]+")

_REEXPORT = "Export the whole collection from ManaBox again as CSV."


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What one ingest did, rendered by the CLI as the success object."""

    collection_path: str
    collection: Collection
    ignored_columns: tuple[str, ...]
    previous: str  # "none", "unreadable", or the previous collection hash
    changes: ChangeReport | None

    def to_dict(self) -> dict[str, Any]:
        lots = self.collection.lots
        binders = Counter((lot.binder_name, lot.binder_type) for lot in lots)
        return {
            "collection": self.collection_path,
            "collection_hash": self.collection.collection_hash,
            "source": {"file": self.collection.source_file, "rows": len(lots)},
            "latest_added": self.collection.latest_added,
            "lots": len(lots),
            "cards": sum(lot.quantity for lot in lots),
            "names": len({lot.name for lot in lots}),
            "printings": len({lot.scryfall_id for lot in lots}),
            "binders": [
                {"name": name, "type": binder_type, "lots": count}
                for (name, binder_type), count in sorted(binders.items())
            ],
            "ignored_columns": list(self.ignored_columns),
            "previous_collection": self.previous,
            "changes": self.changes.to_dict() if self.changes is not None else None,
            "next": self._next_step(),
        }

    def _next_step(self) -> str:
        path = self.collection_path
        if self.previous == "unreadable":
            return (
                "The previous collection could not be read, so there is no change report. "
                f"Review {path} against git diff, then commit it."
            )
        if self.changes is None:
            return f"Review {path}, then commit it."
        if self.previous == self.collection.collection_hash:
            return f"Nothing changed; {path} is already current."
        if self.changes.is_empty:
            return f"No ownership changes; review {path}, then commit it."
        return f"Review changes, then commit {path}."


def ingest(
    export_path: Path, collection_path: Path, *, display_path: str | None = None
) -> IngestResult:
    """Replace the collection at ``collection_path`` with the one derived from
    ``export_path``. Writes nothing unless the whole export is valid."""
    raw = _read_bytes(export_path)
    collection_hash = HASH_PREFIX + hashlib.sha256(raw).hexdigest()
    header, rows = _parse(_decode(raw, export_path), export_path)
    _check_header(header, export_path)
    ignored = tuple(
        column for column in header if column not in REQUIRED_COLUMNS + OPTIONAL_COLUMNS
    )
    if not rows:
        raise ToolError("no_rows", {"path": str(export_path)}, _REEXPORT)
    current = Collection(collection_hash, export_path.name, _build_lots(header, rows, export_path))
    previous, changes = _compare(collection_path, current)
    write(current, collection_path)
    return IngestResult(display_path or str(collection_path), current, ignored, previous, changes)


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        raise ToolError(
            "export_not_found",
            {"path": str(path)},
            "Check the path; it must point at a readable ManaBox export file.",
        ) from None


def _decode(raw: bytes, path: Path) -> str:
    try:
        return raw.decode("utf-8").removeprefix("\ufeff")
    except UnicodeDecodeError as exc:
        raise ToolError(
            "export_not_utf8", {"path": str(path), "byte_offset": exc.start}, _REEXPORT
        ) from None


def _parse(text: str, path: Path) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """Header and data records with their physical line numbers (header is line 1)."""
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader, None)
        if header is None:
            return [], []
        rows = [(reader.line_num, record) for record in reader if record]
    except csv.Error as exc:
        raise ToolError(
            "export_unparseable",
            {"path": str(path), "line": reader.line_num, "message": str(exc)},
            _REEXPORT,
        ) from None
    return header, rows


def _check_header(header: list[str], path: Path) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        raise ToolError(
            "missing_columns",
            {"path": str(path), "missing": missing, "found": header},
            "Export the whole collection from ManaBox again. If ManaBox renamed a column, "
            "update REQUIRED_COLUMNS in deck_composer/ingest.py.",
        )
    duplicated = sorted({column for column in header if header.count(column) > 1})
    if duplicated:
        raise ToolError(
            "duplicate_columns",
            {"path": str(path), "duplicated": duplicated},
            "Export again from ManaBox. If ManaBox now repeats a column, update "
            "deck_composer/ingest.py to say which one to read.",
        )


def _build_lots(
    header: list[str], rows: list[tuple[int, list[str]]], path: Path
) -> tuple[Lot, ...]:
    index = {column: header.index(column) for column in header}
    has_added = "Added" in index

    def value(record: list[str], column: str) -> str:
        position = index[column]
        return record[position] if position < len(record) else ""

    lots: list[Lot] = []
    invalid: list[dict[str, Any]] = []
    for line, record in rows:
        problems = [f"empty:{column}" for column in _TEXT_COLUMNS if not value(record, column)]
        quantity = value(record, "Quantity")
        if not _QUANTITY.fullmatch(quantity) or int(quantity) < 1:
            problems.append("quantity_not_positive_integer")
        if not _UUID.fullmatch(value(record, "Scryfall ID")):
            problems.append("scryfall_id_invalid")
        binder_type = value(record, "Binder Type")
        if binder_type and binder_type not in BINDER_TYPES:
            problems.append(f"binder_type_unknown:{binder_type}")
        if problems:
            invalid.append(
                {
                    "line": line,
                    "name": value(record, "Name"),
                    "set_code": value(record, "Set code"),
                    "collector_number": value(record, "Collector number"),
                    "problems": problems,
                }
            )
            continue
        lots.append(
            Lot(
                name=value(record, "Name"),
                set_code=value(record, "Set code").lower(),
                collector_number=value(record, "Collector number"),
                scryfall_id=value(record, "Scryfall ID"),
                quantity=int(quantity),
                foil=value(record, "Foil"),
                condition=value(record, "Condition"),
                language=value(record, "Language"),
                binder_name=value(record, "Binder Name"),
                binder_type=binder_type,
                added=(value(record, "Added") or None) if has_added else None,
            )
        )
    if invalid:
        next_step = "Fix the listed rows in ManaBox and export again."
        if any(p.startswith("binder_type_unknown") for row in invalid for p in row["problems"]):
            next_step += (
                " A new legitimate Binder Type value means extending BINDER_TYPES in "
                "deck_composer/collection.py."
            )
        raise ToolError(
            "invalid_rows",
            {
                "path": str(path),
                "total": len(invalid),
                "shown": min(len(invalid), ROW_DETAIL_CAP),
                "rows": invalid[:ROW_DETAIL_CAP],
            },
            next_step,
        )
    return tuple(lots)


def _compare(collection_path: Path, current: Collection) -> tuple[str, ChangeReport | None]:
    """The change report against whatever is at ``collection_path``. An absent or
    unreadable previous file never blocks ingest; it only costs the report."""
    try:
        previous = read(collection_path)
    except ToolError as failure:
        return ("none" if failure.error == "collection_not_found" else "unreadable"), None
    return previous.collection_hash, diff(previous, current)
