"""One entry point, one subcommand per module, JSON in and out (ADR-0001).

Success: one JSON object on stdout, exit 0, always with ``next``.
Contract failure: one JSON object on stderr, exit 1.
Usage error: argparse's message on stderr, exit 2.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from deck_composer import cards, scryfall
from deck_composer.errors import ToolError
from deck_composer.ingest import ingest


def project_root(start: Path | None = None) -> Path:
    """The nearest ancestor holding pyproject.toml. Default paths are relative to it,
    so the tool behaves the same from any directory inside the repository."""
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise ToolError(
        "project_root_not_found",
        {"cwd": str(here)},
        "Run deck-composer from inside the repository.",
    )


def _package_version() -> str:
    try:
        return version("deck-composer")
    except PackageNotFoundError:
        return "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deck-composer",
        description="Deterministic tools behind the deck composer skill. Output is JSON.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_package_version()}")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="<subcommand>")
    _add_ingest(subparsers)
    _add_cards(subparsers)
    return parser


def _add_ingest(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "ingest", help="Turn a ManaBox export into the committed collection."
    )
    parser.add_argument("export", type=Path, help="Path to the ManaBox collection export (CSV).")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Where to write the collection. Default: data/collection.json under the project root.",
    )
    parser.set_defaults(handler=_run_ingest)


def _run_ingest(args: argparse.Namespace) -> dict[str, Any]:
    root = project_root()
    out: Path = args.out if args.out is not None else root / "data" / "collection.json"
    return ingest(args.export, out, display_path=_display(out, root)).to_dict()


def _add_cards(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "cards", help="Card facts: build the catalog and rebuild the collection view."
    )
    operations = parser.add_subparsers(dest="operation", required=True, metavar="<operation>")

    enrich = operations.add_parser(
        "enrich", help="Fetch what the catalog lacks for the collection, then rebuild the view."
    )
    enrich.add_argument(
        "--exclude-binder",
        action="append",
        default=None,
        metavar="NAME",
        help="Leave every lot in this binder out of the view. Repeatable.",
    )
    _add_catalog_paths(enrich)
    enrich.set_defaults(handler=_run_enrich)

    refresh = operations.add_parser(
        "refresh", help="Re-fetch every catalog entry and report what changed."
    )
    _add_catalog_paths(refresh)
    refresh.set_defaults(handler=_run_refresh)

    resolve = operations.add_parser(
        "resolve", help="Turn names into exact Scryfall names, one suggestion per miss."
    )
    resolve.add_argument("names", nargs="*", metavar="NAME", help="A name to resolve.")
    resolve.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Read the names from this file, one per line; blank and # lines are ignored.",
    )
    _add_catalog_paths(resolve)
    resolve.set_defaults(handler=_run_resolve, usage_parser=resolve)


def _add_catalog_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Where the catalog lives. Default: data/catalog.json under the project root.",
    )
    parser.add_argument(
        "--view",
        type=Path,
        default=None,
        help="Where to write the view. Default: data/collection_view.tsv under the project root.",
    )


@dataclass(frozen=True, slots=True)
class _CardPaths:
    """The three files every `cards` operation touches, with the root-relative
    spellings the success object reports (R16)."""

    collection: Path
    catalog: Path
    view: Path
    catalog_display: str
    view_display: str


def _card_paths(args: argparse.Namespace) -> _CardPaths:
    root = project_root()
    catalog: Path = args.catalog if args.catalog is not None else root / "data" / "catalog.json"
    view: Path = args.view if args.view is not None else root / "data" / "collection_view.tsv"
    return _CardPaths(
        collection=root / "data" / "collection.json",
        catalog=catalog,
        view=view,
        catalog_display=_display(catalog, root),
        view_display=_display(view, root),
    )


def _client() -> scryfall.Client:
    return scryfall.Client(version=_package_version())


def _run_enrich(args: argparse.Namespace) -> dict[str, Any]:
    paths = _card_paths(args)
    return cards.enrich(
        paths.collection,
        paths.catalog,
        paths.view,
        exclude_binders=tuple(args.exclude_binder or ()),
        client=_client(),
        catalog_display=paths.catalog_display,
        view_display=paths.view_display,
    ).to_dict()


def _run_refresh(args: argparse.Namespace) -> dict[str, Any]:
    paths = _card_paths(args)
    return cards.refresh(
        paths.collection,
        paths.catalog,
        paths.view,
        client=_client(),
        catalog_display=paths.catalog_display,
        view_display=paths.view_display,
    ).to_dict()


def _run_resolve(args: argparse.Namespace) -> dict[str, Any]:
    names = list(args.names)
    if not names and args.file is None:
        args.usage_parser.error("give at least one NAME, or --file PATH holding one name per line")
    paths = _card_paths(args)
    if args.file is not None:
        names.extend(cards.names_from_file(args.file))
    if not names:
        args.usage_parser.error("the file holds no name; give at least one NAME per line")
    return cards.resolve(
        names,
        paths.collection,
        paths.catalog,
        paths.view,
        client=_client(),
        catalog_display=paths.catalog_display,
        view_display=paths.view_display,
    ).to_dict()


def _display(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.handler(args)
    except ToolError as failure:
        print(json.dumps(failure.to_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
