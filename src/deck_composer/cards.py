"""The three `cards` operations: enrich, refresh and resolve.

Owns the operation contract and nothing else: the order of the steps, which
failure each step raises, what the success object carries and what its `next`
sentence says (R15, R16, R17). No Scryfall shape and no file format is known
here: the Scryfall client fetches and projects (R5, R6, R7), the catalog module
reads, merges, replaces and writes (R8, R9, R10), the view module renders
(R11, R12) and the collection module reads and sums (R13). Every operation
ends by rebuilding the view, whether or not the catalog changed (R17).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import replace as _with_fields
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from deck_composer import scryfall
from deck_composer.catalog import (
    Card,
    Catalog,
    RefreshChanges,
    Token,
    merge,
    missing_printings,
    name_mismatches,
)
from deck_composer.catalog import read as read_catalog
from deck_composer.catalog import replace as replace_entries
from deck_composer.catalog import write as write_catalog
from deck_composer.collection import Collection, Lot, owned_by_binder
from deck_composer.collection import read as read_collection
from deck_composer.errors import ToolError
from deck_composer.view import render as render_view
from deck_composer.view import write as write_view

# The advisory in enrich's `next`: a catalog never refreshed, or refreshed
# longer ago than this, is worth refreshing when online (B1).
REFRESH_DAYS = 30

_EMPTY = Catalog(refreshed=None, cards=(), tokens=())
_RECONNECT = "Connect to the network, then run the operation again."
_ALIAS_MAP = (
    "build the alias map (assumption A15) or export the collection from ManaBox again, then "
    "run the operation again."
)


# --- what one operation reports ----------------------------------------------


@dataclass(frozen=True, slots=True)
class EnrichResult:
    """What one enrich did, rendered by the CLI as the success object (B1)."""

    catalog_path: str
    catalog: Catalog
    catalog_written: bool
    previous_catalog: str  # "none", "unreadable" or "readable"
    fetched_printings: int
    fetched_tokens: int
    requests: int
    collection_hash: str
    view_path: str
    view_rows: int
    exclude_binders: tuple[str, ...]
    today: date

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog": self.catalog_path,
            "catalog_written": self.catalog_written,
            "previous_catalog": self.previous_catalog,
            "cards": len(self.catalog.cards),
            "tokens": len(self.catalog.tokens),
            "fetched": {
                "printings": self.fetched_printings,
                "tokens": self.fetched_tokens,
                "requests": self.requests,
            },
            "refreshed": self.catalog.refreshed,
            "collection_hash": self.collection_hash,
            "view": self.view_path,
            "view_rows": self.view_rows,
            "scope": {"exclude_binders": list(self.exclude_binders)},
            "next": self._next_step(),
        }

    def _next_step(self) -> str:
        parts: list[str] = []
        if self.previous_catalog == "unreadable":
            parts.append(
                f"The previous {self.catalog_path} could not be read and was regenerated; "
                "names known only from past resolves return on the next resolve."
            )
        if self.catalog_written:
            parts.append(f"Review {self.catalog_path}, then commit it.")
        else:
            parts.append(f"The catalog at {self.catalog_path} is unchanged.")
        if self.view_rows == 0 and self.exclude_binders:
            parts.append(f"The scope excluded every lot, so {self.view_path} has no rows.")
        else:
            parts.append(f"The view at {self.view_path} is current.")
        if _refresh_due(self.catalog.refreshed, self.today):
            when = (
                "has never been refreshed"
                if self.catalog.refreshed is None
                else f"was last refreshed on {self.catalog.refreshed}"
            )
            parts.append(f"The catalog {when}; run `deck-composer cards refresh` when online.")
        return " ".join(parts)


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """What one refresh did (B3). `changes` is R10's report."""

    catalog_path: str
    catalog: Catalog
    catalog_written: bool
    requests: int
    changes: RefreshChanges
    view_path: str
    view_rows: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog": self.catalog_path,
            "catalog_written": self.catalog_written,
            "cards": len(self.catalog.cards),
            "tokens": len(self.catalog.tokens),
            "requests": self.requests,
            "refreshed": self.catalog.refreshed,
            "changes": self.changes.to_dict(),
            "view": self.view_path,
            "view_rows": self.view_rows,
            "next": self._next_step(),
        }

    def _next_step(self) -> str:
        view = f"The view at {self.view_path} is current."
        if not self.catalog_written:
            return f"Nothing changed; the catalog at {self.catalog_path} is unchanged. {view}"
        if self.changes.is_empty:
            return (
                f"No card fact changed; only the refresh date moved. Review {self.catalog_path}, "
                f"then commit it. {view}"
            )
        return f"Review the changes in {self.catalog_path}, then commit it. {view}"


@dataclass(frozen=True, slots=True)
class Resolution:
    """One input name and what it resolved to (R14). `suggestion` is a hint the
    owner confirms; it is never stored."""

    input: str
    name: str | None
    source: str | None  # "catalog", "scryfall" or None
    suggestion: str | None

    @property
    def status(self) -> str:
        return "resolved" if self.name is not None else "not_found"

    def to_dict(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "name": self.name,
            "status": self.status,
            "source": self.source,
            "suggestion": self.suggestion,
        }


@dataclass(frozen=True, slots=True)
class ResolveResult:
    """What one resolve did (B4). Exit 0 whether or not every name resolved."""

    catalog_path: str
    catalog_written: bool
    results: tuple[Resolution, ...]
    fetched_cards: int
    fetched_tokens: int
    requests: int
    suggestions: int
    view_path: str

    def to_dict(self) -> dict[str, Any]:
        resolved = sum(1 for result in self.results if result.name is not None)
        return {
            "results": [result.to_dict() for result in self.results],
            "resolved": resolved,
            "unresolved": len(self.results) - resolved,
            "fetched": {
                # Resolve fetches by name, never an owned printing by id.
                "printings": 0,
                "cards": self.fetched_cards,
                "tokens": self.fetched_tokens,
                "requests": self.requests,
                "suggestions": self.suggestions,
            },
            "catalog_written": self.catalog_written,
            "view": self.view_path,
            "next": self._next_step(),
        }

    def _next_step(self) -> str:
        unresolved = sum(1 for result in self.results if result.name is None)
        commit = f" Review {self.catalog_path}, then commit it." if self.catalog_written else ""
        if unresolved == 0:
            return f"Every name resolved; use the names as returned.{commit}"
        names = "name" if unresolved == 1 else "names"
        return (
            f"{unresolved} {names} did not resolve; correct each one, confirming any suggestion "
            f"with the owner before using it, then run resolve again.{commit}"
        )


# --- the operations -----------------------------------------------------------


def enrich(
    collection_path: Path,
    catalog_path: Path,
    view_path: Path,
    *,
    exclude_binders: Iterable[str] = (),
    client: scryfall.Client | None = None,
    today: date | None = None,
    catalog_display: str | None = None,
    view_display: str | None = None,
) -> EnrichResult:
    """Fetch what the catalog lacks for the current collection, add it without
    altering an existing entry (R9), then rebuild the view (B1). An absent
    catalog is an empty one; an unreadable or foreign-schema catalog is treated
    as absent and regenerated, which the result reports."""
    collection = read_collection(collection_path)
    previous, known = _previous_catalog(catalog_path)
    excluded = tuple(dict.fromkeys(exclude_binders))
    _check_binders(collection, excluded)
    client = client if client is not None else scryfall.Client()
    hint = _restore_hint(catalog_path) if previous == "unreadable" else ""

    missing = missing_printings(known, collection)
    wanted = tuple(dict.fromkeys(lot.scryfall_id for lot in missing))
    records: list[Card | Token] = []
    tokens_fetched = 0
    if wanted:
        objects, unknown = _fetch(client, _by_id(wanted), printings=len(wanted), hint=hint)
        _check_printings(unknown, missing)
        related = _related(objects, scryfall.project_all(objects), known)
        if related:
            found, lost = _fetch(client, _by_id(related), printings=len(related), hint=hint)
            _check_related(lost)
            objects = [*objects, *found]
            tokens_fetched = len(found)
        records = _link(objects, scryfall.project_all(objects), known)

    merged = merge(known, records)
    _check_names(merged, collection, catalog_written=False)
    # An unreadable catalog is always rewritten, even when nothing was fetched,
    # so a run that succeeds leaves a readable file behind (B1).
    written = merged != known or previous == "unreadable"
    if written:
        write_catalog(merged, catalog_path)
    view_rows = _build_view(collection, merged, view_path, excluded)
    return EnrichResult(
        catalog_path=catalog_display or str(catalog_path),
        catalog=merged,
        catalog_written=written,
        previous_catalog=previous,
        fetched_printings=len(wanted),
        fetched_tokens=tokens_fetched,
        requests=client.requests,
        collection_hash=collection.collection_hash,
        view_path=view_display or str(view_path),
        view_rows=view_rows,
        exclude_binders=excluded,
        today=today or datetime.now(UTC).date(),
    )


def refresh(
    collection_path: Path,
    catalog_path: Path,
    view_path: Path,
    *,
    client: scryfall.Client | None = None,
    today: date | None = None,
    catalog_display: str | None = None,
    view_display: str | None = None,
) -> RefreshResult:
    """Re-fetch every entry, replace every projected field, keep the printings
    and report what moved (R10, B3). The catalog is written before the name
    check, because the fetched names are the truth (R15's one exception).

    Every entry is asked for by one of its printings. The identifier is Brief
    5's latitude, and a Scryfall ID is the one that survives a rename: asking
    by the name the catalog holds would answer nothing for a card Scryfall has
    since renamed, so R10's rename report could never fire."""
    collection = read_collection(collection_path)
    known = read_catalog(catalog_path)
    client = client if client is not None else scryfall.Client()

    entries: tuple[Card | Token, ...] = (*known.cards, *known.tokens)
    identifiers = [{"id": entry.printings[0].scryfall_id} for entry in entries]
    records: list[Card | Token] = []
    if identifiers:
        objects, _ = _fetch(client, identifiers, printings=len(identifiers))
        records = _link(objects, scryfall.project_all(objects), known)

    when = today or datetime.now(UTC).date()
    refreshed, changes = replace_entries(known, records, when.isoformat())
    written = refreshed != known
    if written:
        write_catalog(refreshed, catalog_path)
    _check_names(refreshed, collection, catalog_written=written, changes=changes)
    view_rows = _build_view(collection, refreshed, view_path, ())
    return RefreshResult(
        catalog_path=catalog_display or str(catalog_path),
        catalog=refreshed,
        catalog_written=written,
        requests=client.requests,
        changes=changes,
        view_path=view_display or str(view_path),
        view_rows=view_rows,
    )


def resolve(
    names: Sequence[str],
    collection_path: Path,
    catalog_path: Path,
    view_path: Path,
    *,
    client: scryfall.Client | None = None,
    catalog_display: str | None = None,
    view_display: str | None = None,
) -> ResolveResult:
    """Turn names into exact Scryfall names, from the catalog first and Scryfall
    second, with one suggestion per miss (R14, B4). A miss is reported, never a
    failure: the operation exits 0 whether or not every name resolved."""
    collection = read_collection(collection_path)
    known = _catalog_or_empty(catalog_path)
    client = client if client is not None else scryfall.Client()

    wanted = [name.strip() for name in names]
    found: dict[str, tuple[str, str]] = {}  # folded input -> (name, source)
    for name in wanted:
        entry = known.resolve(name) if name else None
        if entry is not None:
            found[name.casefold()] = (entry.name, "catalog")
    unknown = tuple(dict.fromkeys(name for name in wanted if name and name.casefold() not in found))

    records: list[Card | Token] = []
    cards_fetched = 0
    tokens_fetched = 0
    if unknown:
        objects, _ = _fetch(client, [{"name": name} for name in unknown], names=len(unknown))
        projected = scryfall.project_all(objects)
        cards_fetched = sum(1 for record in projected if isinstance(record, Card))
        related = _related(objects, projected, known)
        if related:
            tokens, lost = _fetch(client, _by_id(related), printings=len(related))
            _check_related(lost)
            objects = [*objects, *tokens]
            tokens_fetched = len(tokens)
        records = _link(objects, scryfall.project_all(objects), known)

    merged = merge(known, records)
    _check_names(merged, collection, catalog_written=False)
    for name in unknown:
        entry = merged.resolve(name)
        if entry is not None:
            found[name.casefold()] = (entry.name, "scryfall")

    suggestions: dict[str, str | None] = {}
    for name in unknown:
        if name.casefold() not in found and name.casefold() not in suggestions:
            suggestions[name.casefold()] = client.fuzzy(name)

    written = merged != known
    if written:
        write_catalog(merged, catalog_path)
    _build_view(collection, merged, view_path, ())
    return ResolveResult(
        catalog_path=catalog_display or str(catalog_path),
        catalog_written=written,
        results=tuple(_resolution(name, found, suggestions) for name in wanted),
        fetched_cards=cards_fetched,
        fetched_tokens=tokens_fetched,
        requests=client.requests,
        suggestions=len(suggestions),
        view_path=view_display or str(view_path),
    )


def names_from_file(path: Path) -> tuple[str, ...]:
    """The names in a resolve list: one per line, blank lines and lines starting
    with `#` ignored (B4). The path is the caller's, never a name."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ToolError(
            "names_file_unreadable",
            {"path": str(path), "message": "no such file"},
            "Give the path of an existing UTF-8 file of names, one per line.",
        ) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise ToolError(
            "names_file_unreadable",
            {"path": str(path), "message": str(exc)},
            "Give the path of a readable UTF-8 file of names, one per line.",
        ) from None
    return tuple(
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


# --- the steps every operation shares -----------------------------------------


def _previous_catalog(path: Path) -> tuple[str, Catalog]:
    """How the catalog on disk was found, and what to build on: enrich alone
    treats an unreadable or foreign-schema catalog as absent (B1, R8)."""
    try:
        return "readable", read_catalog(path)
    except ToolError as failure:
        if failure.error == "catalog_not_found":
            return "none", _EMPTY
        if failure.error in ("catalog_unreadable", "catalog_schema_unknown"):
            return "unreadable", _EMPTY
        raise


def _catalog_or_empty(path: Path) -> Catalog:
    """Resolve's reading of the catalog: absent is empty, unreadable fails (B4)."""
    try:
        return read_catalog(path)
    except ToolError as failure:
        if failure.error == "catalog_not_found":
            return _EMPTY
        raise


def _check_binders(collection: Collection, excluded: tuple[str, ...]) -> None:
    """R12: every `--exclude-binder` name must match a lot, checked before any
    fetch so a typo costs no request."""
    binders = sorted({pair for sums in owned_by_binder(collection).values() for pair in sums})
    present = {name for name, _ in binders}
    unknown = [name for name in excluded if name not in present]
    if unknown:
        raise ToolError(
            "binder_unknown",
            {
                "unknown": unknown,
                "binders": [{"name": name, "type": kind} for name, kind in binders],
            },
            "Pick a binder name from the ones listed under detail.binders, then run the "
            "operation again.",
        )


def _by_id(scryfall_ids: Sequence[str]) -> list[dict[str, str]]:
    return [{"id": scryfall_id} for scryfall_id in scryfall_ids]


def _fetch(
    client: scryfall.Client,
    identifiers: Sequence[Mapping[str, str]],
    *,
    printings: int = 0,
    names: int = 0,
    hint: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One fetch, with what was still missing when the network failed: the client
    knows only the transport's message (Brief 2's `scryfall_unreachable`)."""
    try:
        return client.collection(identifiers)
    except ToolError as failure:
        if failure.error != "scryfall_unreachable":
            raise
        raise ToolError(
            "scryfall_unreachable",
            {
                "missing_printings": printings,
                "missing_names": names,
                "message": failure.detail.get("message", ""),
            },
            _RECONNECT + hint,
        ) from None


def _restore_hint(path: Path) -> str:
    return (
        f" The catalog at {path} could not be read; restore it from git with "
        f"`git checkout {path}` to work offline."
    )


def _related(
    objects: Sequence[Mapping[str, Any]], records: Sequence[Card | Token], known: Catalog
) -> tuple[str, ...]:
    """The related tokens still to fetch (R5): every `token` part of a fetched
    card, less the printings this run already holds and those the catalog owns."""
    fetched = {printing.scryfall_id for record in records for printing in record.printings}
    wanted: list[str] = []
    for obj, record in zip(objects, records, strict=True):
        if not isinstance(record, Card):
            continue
        for scryfall_id in scryfall.related_token_ids(obj):
            if scryfall_id in fetched or scryfall_id in wanted:
                continue
            if known.owner_of(scryfall_id) is None:
                wanted.append(scryfall_id)
    return tuple(wanted)


def _link(
    objects: Sequence[Mapping[str, Any]], records: Sequence[Card | Token], known: Catalog
) -> list[Card | Token]:
    """`project_all` links a card to the tokens fetched beside it; a related token
    the catalog already owns was not fetched again, so its `oracle_id` is added
    here, from the catalog's own entry (R6)."""
    linked: list[Card | Token] = []
    for obj, record in zip(objects, records, strict=True):
        if isinstance(record, Card):
            owned = {
                owner.oracle_id
                for owner in (
                    known.owner_of(scryfall_id) for scryfall_id in scryfall.related_token_ids(obj)
                )
                if isinstance(owner, Token)
            }
            if not owned <= set(record.tokens):
                record = _with_fields(record, tokens=tuple(sorted(set(record.tokens) | owned)))
        linked.append(record)
    return linked


def _check_printings(unknown: Sequence[Mapping[str, Any]], missing: Sequence[Lot]) -> None:
    """An owned printing Scryfall does not know (A20's falsifier): every lot of
    it is named, and nothing is written."""
    lost = {identifier.get("id") for identifier in unknown}
    lots = [lot for lot in missing if lot.scryfall_id in lost]
    if lots:
        raise ToolError(
            "printing_not_found",
            {"lots": [_lot(lot) for lot in lots]},
            "Check each card in ManaBox, re-scan it, then run `deck-composer ingest` and the "
            "operation again.",
        )


def _check_related(unknown: Sequence[Mapping[str, Any]]) -> None:
    """A token a card lists but Scryfall does not return (Brief 2)."""
    if unknown:
        raise ToolError(
            "payload_invalid",
            {
                "scryfall_id": unknown[0].get("id"),
                "field": "all_parts",
                "message": "a related token Scryfall lists was not returned",
            },
            "Scryfall's payload no longer matches what the catalog reads; update the projection "
            "in src/deck_composer/scryfall.py, then run the operation again.",
        )


def _check_names(
    merged: Catalog,
    collection: Collection,
    *,
    catalog_written: bool,
    changes: RefreshChanges | None = None,
) -> None:
    """R3: the collection's names against the catalog's, which are authoritative.
    After a refresh the catalog is already written, and the failure says so."""
    mismatches = name_mismatches(merged, collection)
    if not mismatches:
        return
    detail: dict[str, Any] = {
        "lots": [{**_lot(lot), "catalog_name": name} for lot, name in mismatches],
        "catalog_written": catalog_written,
    }
    if changes is not None:
        detail["changes"] = changes.to_dict()
    lots = "lot" if len(mismatches) == 1 else "lots"
    written = (
        "The catalog holds the new names and the previous view still stands; "
        if catalog_written
        else ""
    )
    raise ToolError(
        "name_mismatch",
        detail,
        f"{written}{len(mismatches)} {lots} carry a name the catalog disagrees with; {_ALIAS_MAP}",
    )


def _lot(lot: Lot) -> dict[str, Any]:
    return {
        "name": lot.name,
        "set_code": lot.set_code,
        "collector_number": lot.collector_number,
        "scryfall_id": lot.scryfall_id,
    }


def _build_view(
    collection: Collection, known: Catalog, path: Path, excluded: tuple[str, ...]
) -> int:
    """R17: every operation rebuilds the view. Answers the number of rows."""
    text = render_view(collection, known, exclude_binders=excluded)
    write_view(text, path)
    return max(text.count("\n") - 3, 0)


def _resolution(
    name: str, found: Mapping[str, tuple[str, str]], suggestions: Mapping[str, str | None]
) -> Resolution:
    resolved = found.get(name.casefold()) if name else None
    if resolved is not None:
        return Resolution(input=name, name=resolved[0], source=resolved[1], suggestion=None)
    return Resolution(
        input=name, name=None, source=None, suggestion=suggestions.get(name.casefold())
    )


def _refresh_due(refreshed: str | None, today: date) -> bool:
    """B1's advisory: a catalog never refreshed, or refreshed longer than
    REFRESH_DAYS ago, is worth refreshing when online."""
    if refreshed is None:
        return True
    try:
        when = date.fromisoformat(refreshed)
    except ValueError:
        return True
    return (today - when).days > REFRESH_DAYS
