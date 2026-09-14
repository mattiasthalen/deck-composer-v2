"""The collection view: the one-line-per-owned-card TSV the composer reads.

Owns `data/collection_view.tsv` (ADR-0005): the two comment lines, the header
and one row per owned card, joining the collection's lots with the catalog's
cards through each lot's printing (its `scryfall_id`, via `Catalog.owner_of`),
under the scope (R13). Rebuilt whole by every `cards` operation, never
committed (R11, R12, R17). Tokens are never resolution targets here: a lot
whose printing belongs to a token has no owning `Card` and contributes no
row, even when a card of the same name exists elsewhere in the catalog.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

from deck_composer.catalog import Card, Catalog
from deck_composer.collection import Collection
from deck_composer.errors import ToolError

_HEADER = ("name", "qty", "ci", "type", "cmc", "legal", "gc", "rank", "sets", "text")
_CI_ORDER = "WUBRG"
_PAREN = re.compile(r"\([^()]*\)")
_WHITESPACE = re.compile(r"\s+")


def render(collection: Collection, catalog: Catalog, *, exclude_binders: Iterable[str] = ()) -> str:
    """R11, R12: the view's bytes. The caller guarantees coverage: every owned
    printing is in the catalog. Each lot is joined through its printing (via
    `Catalog.owner_of`), never by name alone. A lot whose printing belongs to
    a token contributes no row, even when a card of the same name exists."""
    excluded_binders = tuple(exclude_binders)
    excluded = set(excluded_binders)
    totals: dict[str, int] = {}
    cards_by_name: dict[str, Card] = {}
    remaining_sets: dict[str, set[str]] = {}
    for lot in collection.lots:
        if lot.binder_name in excluded:
            continue
        owner = catalog.owner_of(lot.scryfall_id)
        if not isinstance(owner, Card):
            continue
        totals[owner.name] = totals.get(owner.name, 0) + lot.quantity
        cards_by_name[owner.name] = owner
        remaining_sets.setdefault(owner.name, set()).add(lot.set_code)

    lines = [
        f"# collection view · collection {collection.collection_hash} · "
        f"catalog refreshed {catalog.refreshed or 'never'} · scope {_scope(excluded_binders)}",
        "# derived from data/collection.json and data/catalog.json by deck-composer cards; "
        "regenerated on every run, never committed",
        "\t".join(_HEADER),
    ]
    for name in sorted(totals):
        quantity = totals[name]
        if quantity <= 0:
            continue
        card = cards_by_name[name]
        lines.append("\t".join(_row(name, quantity, card, remaining_sets.get(name, set()))))
    return "\n".join(lines) + "\n"


def _scope(excluded_binders: tuple[str, ...]) -> str:
    if not excluded_binders:
        return "none"
    return " ".join(f'exclude-binder "{name}"' for name in excluded_binders)


def _row(name: str, quantity: int, card: Card, sets: set[str]) -> tuple[str, ...]:
    return (
        name,
        str(quantity),
        _color_identity(card.color_identity),
        card.type_line,
        _cmc(card.cmc),
        card.legality,
        "GC" if card.game_changer else "",
        str(card.edhrec_rank) if card.edhrec_rank is not None else "",
        ",".join(sorted(sets)),
        _text(card),
    )


def _color_identity(colors: tuple[str, ...]) -> str:
    letters = "".join(letter for letter in _CI_ORDER if letter in colors)
    return letters or "C"


def _cmc(value: float) -> str:
    if isinstance(value, int):
        return str(value)
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def _text(card: Card) -> str:
    if card.faces is not None:
        parts = [_clean(face.oracle_text) for face in card.faces]
    else:
        parts = [_clean(card.oracle_text)]
    return " // ".join(parts)


def _clean(text: str | None) -> str:
    """Reminder text removed, whitespace it leaves behind collapsed, newlines
    and tabs replaced so the cell stays one record (R11, Brief 4)."""
    if not text:
        return ""
    text = text.replace("\n", " / ").replace("\t", " ")
    text = _PAREN.sub("", text)
    return _WHITESPACE.sub(" ", text).strip()


def write(text: str, path: Path) -> None:
    """All-or-nothing: `path` holds the previous file or the new one, never a
    partial (R15)."""
    temporary = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    except OSError as exc:
        raise ToolError(
            "view_write_failed",
            {"path": str(path), "message": str(exc)},
            "Fix the filesystem problem, then run the operation again.",
        ) from None
