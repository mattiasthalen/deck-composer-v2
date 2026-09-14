"""The catalog: Scryfall facts for every card and token the project has seen.

Owns `data/catalog.json` (ADR-0003): schema, the record shapes (`Printing`,
`Face`, `Card`, `Token`), the `Catalog` container and its four lookups. File
IO, `merge` and `replace` are added by WP2; this module carries the records
only until then.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SCHEMA = 1


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
