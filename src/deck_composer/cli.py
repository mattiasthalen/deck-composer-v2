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
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

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
