"""The collection file: schema, read, write, diff by lot key and sum by name.

Owns the format of ``data/collection.json`` (ADR-0002). Ingest builds a
``Collection`` from a ManaBox export; card data and the table store read it
through this module and never parse the file themselves. Provides ownership
sums: by name with optional binder exclusion, and by name and binder pair.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deck_composer.errors import ToolError

SCHEMA = 1
HASH_PREFIX = "sha256:"
# Closed vocabulary. ManaBox emits "binder" today; "deck" is what scoping by
# ManaBox deck relies on (assumption A17). Any other value fails ingest loudly.
BINDER_TYPES: tuple[str, ...] = ("binder", "deck")

_RE_INGEST = "Export the whole collection from ManaBox again and run `deck-composer ingest`."

LotKey = tuple[str, str, str, str, str, str]


@dataclass(frozen=True, slots=True)
class Lot:
    """One export row. Physical attributes never matter to composition (A9)."""

    name: str
    set_code: str
    collector_number: str
    scryfall_id: str
    quantity: int
    foil: str
    condition: str
    language: str
    binder_name: str
    binder_type: str
    added: str | None

    @property
    def key(self) -> LotKey:
        """What the change report compares on. ``added`` is deliberately outside it."""
        return (
            self.scryfall_id,
            self.foil,
            self.condition,
            self.language,
            self.binder_name,
            self.binder_type,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "set_code": self.set_code,
            "collector_number": self.collector_number,
            "scryfall_id": self.scryfall_id,
            "quantity": self.quantity,
            "foil": self.foil,
            "condition": self.condition,
            "language": self.language,
            "binder_name": self.binder_name,
            "binder_type": self.binder_type,
            "added": self.added,
        }


def _sort_key(lot: Lot) -> tuple[str, str, str, str, str, str, str, str, bool, str]:
    return (
        lot.name,
        lot.set_code,
        lot.collector_number,
        lot.foil,
        lot.condition,
        lot.language,
        lot.binder_name,
        lot.binder_type,
        lot.added is None,
        lot.added or "",
    )


@dataclass(frozen=True, slots=True)
class Collection:
    """The normalized ownership record derived from one export. Lots are always
    held sorted, so the same lots give the same file (R8, R9)."""

    collection_hash: str
    source_file: str
    lots: tuple[Lot, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "lots", tuple(sorted(self.lots, key=_sort_key)))

    @property
    def latest_added(self) -> str | None:
        values = [lot.added for lot in self.lots if lot.added is not None]
        return max(values) if values else None


def owned_by_name(collection: Collection, *, exclude_binders: Iterable[str] = ()) -> dict[str, int]:
    """Quantity per card name, excluding lots whose binder_name is in the set.

    Omit exclude_binders for all lots; pass an iterable to exclude matching
    binders regardless of type. A lot is excluded when its binder_name equals
    one of the excluded names, code-point-exactly (R12).
    """
    excluded = set(exclude_binders)
    totals: dict[str, int] = {}
    for lot in collection.lots:
        if lot.binder_name not in excluded:
            totals[lot.name] = totals.get(lot.name, 0) + lot.quantity
    return totals


def owned_by_binder(collection: Collection) -> dict[str, dict[tuple[str, str], int]]:
    """Quantity per card name and per (binder_name, binder_type) pair.

    Returns a dictionary mapping each card name to a dictionary mapping
    (binder_name, binder_type) tuples to quantities. R13 requirement.
    """
    totals: dict[str, dict[tuple[str, str], int]] = {}
    for lot in collection.lots:
        if lot.name not in totals:
            totals[lot.name] = {}
        key = (lot.binder_name, lot.binder_type)
        totals[lot.name][key] = totals[lot.name].get(key, 0) + lot.quantity
    return totals


@dataclass(frozen=True, slots=True)
class ChangeReport:
    """What changed between two collections, by lot key and by card name."""

    previous_hash: str
    lots_added: int
    lots_removed: int
    lots_quantity_changed: int
    cards_delta: int
    names_added: tuple[str, ...]
    names_removed: tuple[str, ...]
    names_quantity_changed: tuple[tuple[str, int, int], ...]

    @property
    def is_empty(self) -> bool:
        return not (
            self.lots_added
            or self.lots_removed
            or self.lots_quantity_changed
            or self.names_added
            or self.names_removed
            or self.names_quantity_changed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_hash": self.previous_hash,
            "lots": {
                "added": self.lots_added,
                "removed": self.lots_removed,
                "quantity_changed": self.lots_quantity_changed,
            },
            "cards_delta": self.cards_delta,
            "names": {
                "added": list(self.names_added),
                "removed": list(self.names_removed),
                "quantity_changed": [
                    {"name": name, "from": before, "to": after}
                    for name, before, after in self.names_quantity_changed
                ],
            },
        }


def _quantity_by_key(collection: Collection) -> dict[LotKey, int]:
    totals: dict[LotKey, int] = {}
    for lot in collection.lots:
        totals[lot.key] = totals.get(lot.key, 0) + lot.quantity
    return totals


def diff(previous: Collection, current: Collection) -> ChangeReport:
    """Compare two collections. Duplicate lot keys are summed before comparing."""
    before, after = _quantity_by_key(previous), _quantity_by_key(current)
    names_before, names_after = owned_by_name(previous), owned_by_name(current)
    shared_names = sorted(set(names_before) & set(names_after))
    return ChangeReport(
        previous_hash=previous.collection_hash,
        lots_added=sum(1 for key in after if key not in before),
        lots_removed=sum(1 for key in before if key not in after),
        lots_quantity_changed=sum(
            1 for key in after if key in before and before[key] != after[key]
        ),
        cards_delta=sum(names_after.values()) - sum(names_before.values()),
        names_added=tuple(sorted(set(names_after) - set(names_before))),
        names_removed=tuple(sorted(set(names_before) - set(names_after))),
        names_quantity_changed=tuple(
            (name, names_before[name], names_after[name])
            for name in shared_names
            if names_before[name] != names_after[name]
        ),
    )


def render(collection: Collection) -> str:
    """Schema 1, one lot per line, fixed key order, LF. Locked by a golden test."""
    lots = collection.lots
    source = {"file": collection.source_file, "rows": len(lots)}
    lines = [
        "{",
        f'  "schema": {SCHEMA},',
        f'  "collection_hash": {json.dumps(collection.collection_hash)},',
        f'  "source": {json.dumps(source, ensure_ascii=False)},',
        f'  "latest_added": {json.dumps(collection.latest_added)},',
        '  "lots": [',
    ]
    for index, lot in enumerate(lots):
        comma = "," if index < len(lots) - 1 else ""
        lines.append(f"    {json.dumps(lot.to_dict(), ensure_ascii=False)}{comma}")
    lines += ["  ]", "}"]
    return "\n".join(lines) + "\n"


def write(collection: Collection, path: Path) -> None:
    """All-or-nothing: ``path`` holds the previous file or the new one, never a partial."""
    temporary = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(render(collection), encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    except OSError as exc:
        raise ToolError(
            "collection_write_failed",
            {"path": str(path), "message": str(exc)},
            "Fix the filesystem problem and run ingest again.",
        ) from None


def _lot_from_dict(item: dict[str, Any]) -> Lot:
    return Lot(
        name=item["name"],
        set_code=item["set_code"],
        collector_number=item["collector_number"],
        scryfall_id=item["scryfall_id"],
        quantity=int(item["quantity"]),
        foil=item["foil"],
        condition=item["condition"],
        language=item["language"],
        binder_name=item["binder_name"],
        binder_type=item["binder_type"],
        added=item.get("added"),
    )


def read(path: Path) -> Collection:
    """Load a committed collection. Fails loudly on an unknown schema (R15); does not
    re-validate lot values, which entered through ingest."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ToolError(
            "collection_not_found",
            {"path": str(path)},
            "Run `deck-composer ingest <export>` on the current ManaBox export.",
        ) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise ToolError(
            "collection_unreadable", {"path": str(path), "message": str(exc)}, _RE_INGEST
        ) from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ToolError(
            "collection_unreadable", {"path": str(path), "message": str(exc)}, _RE_INGEST
        ) from None
    if not isinstance(data, dict):
        raise ToolError(
            "collection_unreadable",
            {"path": str(path), "message": "top level is not an object"},
            _RE_INGEST,
        )
    schema = data.get("schema")
    if schema != SCHEMA:
        raise ToolError(
            "collection_schema_unknown", {"path": str(path), "schema": schema}, _RE_INGEST
        )
    try:
        return Collection(
            collection_hash=data["collection_hash"],
            source_file=data["source"]["file"],
            lots=tuple(_lot_from_dict(item) for item in data["lots"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolError(
            "collection_unreadable",
            {"path": str(path), "message": f"malformed collection: {exc!r}"},
            _RE_INGEST,
        ) from None
