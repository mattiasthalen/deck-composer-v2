"""The catalog file: schema, the record shapes, read, write, merge and replace.

Owns ``data/catalog.json`` (ADR-0003): the entry shapes (`Printing`, `Face`,
`Card`, `Token`), the `Catalog` container with its four lookups, the file's
byte layout, and the two ways the catalog grows. The Scryfall client projects
payloads into these records; card data and every later consumer read the file
through `read` and never parse it themselves. Enrich adds through `merge`,
which never alters an existing entry beyond appending an unseen printing (R9);
refresh goes through `replace`, which swaps every fetched field, keeps the
printings already listed and reports what moved (R10). The two checks a
collection must pass against the catalog, coverage (R4) and name authority
(R3), live here as `missing_printings` and `name_mismatches`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from dataclasses import replace as _with_fields
from pathlib import Path
from typing import Any

from deck_composer.collection import Collection, Lot
from deck_composer.errors import ToolError

SCHEMA = 1

_RE_ENRICH = "Run `deck-composer cards enrich` while online to build the catalog."
_RE_REGENERATE = (
    "Run `deck-composer cards enrich` while online to regenerate the catalog, or restore the "
    "file from git."
)


@dataclass(frozen=True, slots=True)
class Printing:
    """One printing: a Scryfall ID and the fields R6 keeps about it."""

    scryfall_id: str
    set: str
    set_type: str
    collector_number: str
    rarity: str
    released_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scryfall_id": self.scryfall_id,
            "set": self.set,
            "set_type": self.set_type,
            "collector_number": self.collector_number,
            "rarity": self.rarity,
            "released_at": self.released_at,
        }


def _sorted_printings(printings: Iterable[Printing]) -> tuple[Printing, ...]:
    """Printings inside an entry are held sorted by Scryfall ID, so the same
    printings give the same line (R8)."""
    return tuple(sorted(printings, key=lambda printing: printing.scryfall_id))


@dataclass(frozen=True, slots=True)
class Face:
    """One face of a multi-faced card. Never referenced on its own (Brief 3)."""

    name: str
    mana_cost: str | None
    type_line: str | None
    colors: tuple[str, ...] | None
    oracle_text: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mana_cost": self.mana_cost,
            "type_line": self.type_line,
            "colors": list(self.colors) if self.colors is not None else None,
            "oracle_text": self.oracle_text,
        }


@dataclass(frozen=True, slots=True)
class Card:
    """A card entry, identified by its exact Scryfall name (R2)."""

    name: str
    oracle_id: str
    layout: str
    type_line: str
    mana_cost: str | None
    cmc: float
    colors: tuple[str, ...] | None
    color_identity: tuple[str, ...]
    produced_mana: tuple[str, ...] | None
    oracle_text: str | None
    keywords: tuple[str, ...]
    legality: str
    game_changer: bool
    edhrec_rank: int | None
    faces: tuple[Face, ...] | None
    tokens: tuple[str, ...]
    printings: tuple[Printing, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "printings", _sorted_printings(self.printings))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "oracle_id": self.oracle_id,
            "layout": self.layout,
            "type_line": self.type_line,
            "mana_cost": self.mana_cost,
            "cmc": self.cmc,
            "colors": list(self.colors) if self.colors is not None else None,
            "color_identity": list(self.color_identity),
            "produced_mana": list(self.produced_mana) if self.produced_mana is not None else None,
            "oracle_text": self.oracle_text,
            "keywords": list(self.keywords),
            "legality": self.legality,
            "game_changer": self.game_changer,
            "edhrec_rank": self.edhrec_rank,
            "faces": [face.to_dict() for face in self.faces] if self.faces is not None else None,
            "tokens": list(self.tokens),
            "printings": [printing.to_dict() for printing in self.printings],
        }


@dataclass(frozen=True, slots=True)
class Token:
    """A token entry, identified by its `oracle_id` (never a deck candidate)."""

    oracle_id: str
    name: str
    layout: str
    type_line: str
    oracle_text: str | None
    printings: tuple[Printing, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "printings", _sorted_printings(self.printings))

    def to_dict(self) -> dict[str, Any]:
        return {
            "oracle_id": self.oracle_id,
            "name": self.name,
            "layout": self.layout,
            "type_line": self.type_line,
            "oracle_text": self.oracle_text,
            "printings": [printing.to_dict() for printing in self.printings],
        }


@dataclass(frozen=True, slots=True)
class Catalog:
    """The whole catalog: a union over time, never a snapshot (Brief 3). Entries are
    always held sorted, so the same entries give the same file (R8)."""

    refreshed: str | None
    cards: tuple[Card, ...]
    tokens: tuple[Token, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "cards", tuple(sorted(self.cards, key=lambda card: card.name)))
        object.__setattr__(
            self, "tokens", tuple(sorted(self.tokens, key=lambda token: token.oracle_id))
        )

    def card(self, name: str) -> Card | None:
        """Exact lookup by the card's Scryfall name."""
        for entry in self.cards:
            if entry.name == name:
                return entry
        return None

    def token(self, oracle_id: str) -> Token | None:
        """Exact lookup by the token's `oracle_id`."""
        for entry in self.tokens:
            if entry.oracle_id == oracle_id:
                return entry
        return None

    def owner_of(self, scryfall_id: str) -> Card | Token | None:
        """The card or token whose printings include this Scryfall ID."""
        for entry in self.cards:
            for printing in entry.printings:
                if printing.scryfall_id == scryfall_id:
                    return entry
        for entry in self.tokens:
            for printing in entry.printings:
                if printing.scryfall_id == scryfall_id:
                    return entry
        return None

    def resolve(self, name: str) -> Card | None:
        """R14's local rule: case-insensitive over every card name and every face
        name; a full-name match wins over a face-name match. Tokens are never
        resolution targets."""
        folded = name.casefold()
        for entry in self.cards:
            if entry.name.casefold() == folded:
                return entry
        for entry in self.cards:
            if entry.faces is not None:
                for face in entry.faces:
                    if face.name.casefold() == folded:
                        return entry
        return None


@dataclass(frozen=True, slots=True)
class RefreshChanges:
    """What one refresh moved: the report R10 requires, as tuples so the record
    is hashable and ordered. Entries Scryfall did not return are kept unchanged
    and named under `unresolved`."""

    legality: tuple[tuple[str, str, str], ...]
    game_changer: tuple[tuple[str, bool, bool], ...]
    text: tuple[str, ...]
    renamed: tuple[tuple[str, str], ...]
    unresolved: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not (
            self.legality or self.game_changer or self.text or self.renamed or self.unresolved
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "legality": [
                {"name": name, "from": before, "to": after} for name, before, after in self.legality
            ],
            "game_changer": [
                {"name": name, "from": before, "to": after}
                for name, before, after in self.game_changer
            ],
            "text": list(self.text),
            "renamed": [{"from": before, "to": after} for before, after in self.renamed],
            "unresolved": list(self.unresolved),
        }


# --- the file ----------------------------------------------------------------


def render(catalog: Catalog) -> str:
    """Schema 1, one entry per line, fixed key order, LF, non-ASCII verbatim.
    Locked by a golden test (R8)."""
    lines = [
        "{",
        f'  "schema": {SCHEMA},',
        f'  "refreshed": {json.dumps(catalog.refreshed)},',
    ]
    lines += _section("cards", [card.to_dict() for card in catalog.cards], last=False)
    lines += _section("tokens", [token.to_dict() for token in catalog.tokens], last=True)
    lines.append("}")
    return "\n".join(lines) + "\n"


def _section(name: str, entries: list[dict[str, Any]], *, last: bool) -> list[str]:
    lines = [f'  "{name}": [']
    for index, entry in enumerate(entries):
        comma = "," if index < len(entries) - 1 else ""
        lines.append(f"    {json.dumps(entry, ensure_ascii=False)}{comma}")
    lines.append("  ]" if last else "  ],")
    return lines


def write(catalog: Catalog, path: Path) -> None:
    """All-or-nothing: ``path`` holds the previous file or the new one, never a partial."""
    temporary = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(render(catalog), encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    except OSError as exc:
        raise ToolError(
            "catalog_write_failed",
            {"path": str(path), "message": str(exc)},
            "Fix the filesystem problem, then run the operation again.",
        ) from None


def read(path: Path) -> Catalog:
    """Load the committed catalog. Fails loudly on an unknown schema (R8); does not
    re-validate entry values, which entered through the Scryfall client. Unknown
    keys, top level or inside an entry, are ignored."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ToolError("catalog_not_found", {"path": str(path)}, _RE_ENRICH) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise _unreadable(path, str(exc)) from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _unreadable(path, str(exc)) from None
    if not isinstance(data, dict):
        raise _unreadable(path, "top level is not an object")
    schema = data.get("schema")
    if schema != SCHEMA:
        raise ToolError(
            "catalog_schema_unknown",
            {"path": str(path), "schema": schema},
            "Run `deck-composer cards enrich` while online to regenerate the catalog.",
        )
    for section in ("cards", "tokens"):
        if not isinstance(data.get(section), list):
            raise _unreadable(path, f"no list of entries under {section!r}")
    try:
        return Catalog(
            refreshed=data.get("refreshed"),
            cards=tuple(_card_from_dict(entry) for entry in data["cards"]),
            tokens=tuple(_token_from_dict(entry) for entry in data["tokens"]),
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise _unreadable(path, f"malformed entry: {exc!r}") from None


def _unreadable(path: Path, message: str) -> ToolError:
    return ToolError("catalog_unreadable", {"path": str(path), "message": message}, _RE_REGENERATE)


def _printing_from_dict(item: dict[str, Any]) -> Printing:
    return Printing(
        scryfall_id=item["scryfall_id"],
        set=item["set"],
        set_type=item["set_type"],
        collector_number=item["collector_number"],
        rarity=item["rarity"],
        released_at=item["released_at"],
    )


def _face_from_dict(item: dict[str, Any]) -> Face:
    return Face(
        name=item["name"],
        mana_cost=item["mana_cost"],
        type_line=item["type_line"],
        colors=_optional_tuple(item["colors"]),
        oracle_text=item["oracle_text"],
    )


def _card_from_dict(item: dict[str, Any]) -> Card:
    faces = item["faces"]
    return Card(
        name=item["name"],
        oracle_id=item["oracle_id"],
        layout=item["layout"],
        type_line=item["type_line"],
        mana_cost=item["mana_cost"],
        cmc=item["cmc"],
        colors=_optional_tuple(item["colors"]),
        color_identity=tuple(item["color_identity"]),
        produced_mana=_optional_tuple(item["produced_mana"]),
        oracle_text=item["oracle_text"],
        keywords=tuple(item["keywords"]),
        legality=item["legality"],
        game_changer=item["game_changer"],
        edhrec_rank=item["edhrec_rank"],
        faces=tuple(_face_from_dict(face) for face in faces) if faces is not None else None,
        tokens=tuple(item["tokens"]),
        printings=tuple(_printing_from_dict(printing) for printing in item["printings"]),
    )


def _token_from_dict(item: dict[str, Any]) -> Token:
    return Token(
        oracle_id=item["oracle_id"],
        name=item["name"],
        layout=item["layout"],
        type_line=item["type_line"],
        oracle_text=item["oracle_text"],
        printings=tuple(_printing_from_dict(printing) for printing in item["printings"]),
    )


def _optional_tuple(value: list[str] | None) -> tuple[str, ...] | None:
    return None if value is None else tuple(value)


# --- how the catalog grows ----------------------------------------------------


def merge(catalog: Catalog, fetched: Sequence[Card | Token]) -> Catalog:
    """Enrich's semantics (R9): add cards and tokens the catalog lacks, append
    printings it has not seen, and change nothing else. A printing already listed
    under some entry is never appended to another (Brief 3). A name that would
    carry a second `oracle_id` fails with `name_collision` (R2)."""
    cards = list(catalog.cards)
    tokens = list(catalog.tokens)
    by_name = {card.name: index for index, card in enumerate(cards)}
    by_oracle = {token.oracle_id: index for index, token in enumerate(tokens)}
    seen = _printing_ids(catalog)
    for record in fetched:
        # Only a printing no entry owns yet may join an entry; a new entry falls
        # back to its own printings, since an entry without one cannot exist.
        unseen = _unseen(record, seen)
        if isinstance(record, Card):
            index = by_name.get(record.name)
            if index is None:
                by_name[record.name] = len(cards)
                cards.append(_with_fields(record, printings=unseen or record.printings))
            else:
                if cards[index].oracle_id != record.oracle_id:
                    raise _name_collision(record.name, cards[index].oracle_id, record.oracle_id)
                cards[index] = _add_printings(cards[index], unseen)
        else:
            index = by_oracle.get(record.oracle_id)
            if index is None:
                by_oracle[record.oracle_id] = len(tokens)
                tokens.append(_with_fields(record, printings=unseen or record.printings))
            else:
                tokens[index] = _add_printings(tokens[index], unseen)
        seen.update(printing.scryfall_id for printing in record.printings)
    return Catalog(refreshed=catalog.refreshed, cards=tuple(cards), tokens=tuple(tokens))


def replace(
    catalog: Catalog, fetched: Sequence[Card | Token], refreshed: str
) -> tuple[Catalog, RefreshChanges]:
    """Refresh's semantics (R10): every fetched entry replaces its counterpart's
    fields, keeps the printings already listed and adds the fetched one, and the
    catalog's date becomes `refreshed`. Counterparts are matched by `oracle_id`,
    so a rename is a change of the name, not a new entry. An entry Scryfall did
    not return is kept unchanged and named under `unresolved`; no entry is ever
    removed."""
    fetched_cards = _fold(record for record in fetched if isinstance(record, Card))
    fetched_tokens = _fold(record for record in fetched if isinstance(record, Token))
    legality: list[tuple[str, str, str]] = []
    game_changer: list[tuple[str, bool, bool]] = []
    text: list[str] = []
    renamed: list[tuple[str, str]] = []
    unresolved: list[str] = []

    cards: list[Card] = []
    for entry in catalog.cards:
        replacement = fetched_cards.pop(entry.oracle_id, None)
        if replacement is None:
            cards.append(entry)
            unresolved.append(entry.name)
            continue
        updated = _add_printings(replacement, entry.printings)
        if entry.legality != updated.legality:
            legality.append((updated.name, entry.legality, updated.legality))
        if entry.game_changer != updated.game_changer:
            game_changer.append((updated.name, entry.game_changer, updated.game_changer))
        if _oracle_texts(entry) != _oracle_texts(updated):
            text.append(updated.name)
        if entry.name != updated.name:
            renamed.append((entry.name, updated.name))
        cards.append(updated)
    cards.extend(fetched_cards.values())

    tokens: list[Token] = []
    for token in catalog.tokens:
        replacement_token = fetched_tokens.pop(token.oracle_id, None)
        if replacement_token is None:
            tokens.append(token)
            unresolved.append(token.name)
            continue
        tokens.append(_add_printings(replacement_token, token.printings))
    tokens.extend(fetched_tokens.values())

    _check_names(cards)
    changes = RefreshChanges(
        legality=tuple(sorted(legality)),
        game_changer=tuple(sorted(game_changer)),
        text=tuple(sorted(text)),
        renamed=tuple(sorted(renamed)),
        unresolved=tuple(sorted(unresolved)),
    )
    return Catalog(refreshed=refreshed, cards=tuple(cards), tokens=tuple(tokens)), changes


def _fold[E: (Card, Token)](records: Iterable[E]) -> dict[str, E]:
    """One record per `oracle_id`: two printings of one card come back as two
    objects, and refresh replaces one entry from both."""
    folded: dict[str, E] = {}
    for record in records:
        known = folded.get(record.oracle_id)
        folded[record.oracle_id] = (
            record if known is None else _add_printings(known, record.printings)
        )
    return folded


def _add_printings[E: (Card, Token)](entry: E, printings: Iterable[Printing]) -> E:
    listed = {printing.scryfall_id for printing in entry.printings}
    extra = tuple(printing for printing in printings if printing.scryfall_id not in listed)
    return entry if not extra else _with_fields(entry, printings=entry.printings + extra)


def _unseen(record: Card | Token, seen: set[str]) -> tuple[Printing, ...]:
    """The record's printings no entry owns yet."""
    return tuple(printing for printing in record.printings if printing.scryfall_id not in seen)


def _printing_ids(catalog: Catalog) -> set[str]:
    return {
        printing.scryfall_id
        for entry in (*catalog.cards, *catalog.tokens)
        for printing in entry.printings
    }


def _oracle_texts(card: Card) -> tuple[str | None, ...]:
    faces = card.faces or ()
    return (card.oracle_text, *(face.oracle_text for face in faces))


def _check_names(cards: Iterable[Card]) -> None:
    oracle_ids: dict[str, str] = {}
    for card in cards:
        known = oracle_ids.setdefault(card.name, card.oracle_id)
        if known != card.oracle_id:
            raise _name_collision(card.name, known, card.oracle_id)


def _name_collision(name: str, first: str, second: str) -> ToolError:
    return ToolError(
        "name_collision",
        {"name": name, "oracle_ids": [first, second]},
        f"Two Scryfall cards carry the name {name}; decide a disambiguation rule for the "
        "catalog before running the operation again.",
    )


# --- what a collection must satisfy -------------------------------------------


def missing_printings(catalog: Catalog, collection: Collection) -> tuple[Lot, ...]:
    """The coverage gap (R4): every lot whose Scryfall ID no entry owns, in the
    collection's order. Two lots of one printing are two entries here; a caller
    fetching them takes the distinct Scryfall IDs."""
    owned = _printing_ids(catalog)
    return tuple(lot for lot in collection.lots if lot.scryfall_id not in owned)


def name_mismatches(catalog: Catalog, collection: Collection) -> tuple[tuple[Lot, str], ...]:
    """Name authority (R3): every lot whose name differs, code point for code
    point, from the catalog name of the entry owning its printing, paired with
    that catalog name. A lot no entry covers is a coverage gap, not a mismatch."""
    names = {
        printing.scryfall_id: entry.name
        for entry in (*catalog.cards, *catalog.tokens)
        for printing in entry.printings
    }
    return tuple(
        (lot, names[lot.scryfall_id])
        for lot in collection.lots
        if lot.scryfall_id in names and names[lot.scryfall_id] != lot.name
    )
