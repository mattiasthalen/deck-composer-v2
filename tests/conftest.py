"""Fixtures: the base export as rows, and a fake project root with the cwd inside it."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import BASE, Header, Rows, parse


@pytest.fixture
def base() -> tuple[Header, Rows]:
    return parse(BASE.read_text(encoding="utf-8"))


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake project root with the cwd inside it."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fake'\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path
