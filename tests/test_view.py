"""The collection view: byte-exact golden, row shape, scope, determinism."""

from __future__ import annotations

from pathlib import Path

import pytest

from deck_composer.catalog import Card, Catalog, Token
from deck_composer.collection import read as read_collection
from deck_composer.errors import ToolError
from deck_composer.scryfall import project_all
from deck_composer.view import render, write
from tests.helpers import FIXTURES, GOLDEN, load_scryfall_fixture

GOLDEN_VIEW = FIXTURES / "golden" / "manabox_base.view.tsv"


@pytest.fixture
def catalog() -> Catalog:
    records = project_all(load_scryfall_fixture())
    cards = tuple(record for record in records if isinstance(record, Card))
    tokens = tuple(record for record in records if isinstance(record, Token))
    return Catalog(None, cards, tokens)


def test_base_fixture_matches_golden_byte_for_byte(catalog: Catalog) -> None:
    collection = read_collection(GOLDEN)
    text = render(collection, catalog)
    assert text == GOLDEN_VIEW.read_text(encoding="utf-8")


def test_golden_shape(catalog: Catalog) -> None:
    lines = GOLDEN_VIEW.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("# collection view")
    assert "collection sha256:" in lines[0]
    assert "catalog refreshed never" in lines[0]
    assert lines[1].startswith("#")
    assert lines[2] == "name\tqty\tci\ttype\tcmc\tlegal\tgc\trank\tsets\ttext"
    for line in lines[3:]:
        assert len(line.split("\t")) == 10


def test_rows_sorted_no_tokens_no_zero_quantity(catalog: Catalog) -> None:
    lines = GOLDEN_VIEW.read_text(encoding="utf-8").splitlines()[3:]
    names = [line.split("\t")[0] for line in lines]
    assert names == sorted(names)
    assert "Splash Lasher" not in names
    assert "Snail" not in names
    for line in lines:
        assert line.split("\t")[1] != "0"


def _row(catalog: Catalog, collection_hash_lines: list[str], name: str) -> list[str]:
    for line in collection_hash_lines:
        cells = line.split("\t")
        if cells[0] == name:
            return cells
    raise AssertionError(f"no row for {name}")


def test_wick_row(catalog: Catalog) -> None:
    lines = GOLDEN_VIEW.read_text(encoding="utf-8").splitlines()[3:]
    cells = _row(catalog, lines, "Wick, the Whorled Mind")
    assert cells[2] == "UBR"
    assert cells[4] == "4"
    assert cells[5] == "legal"
    assert cells[6] == ""
    assert cells[8] == "blb"
    assert "\n" not in cells[9]
    assert "\t" not in cells[9]
    assert "(" not in cells[9]


def test_basic_land_row(catalog: Catalog) -> None:
    lines = GOLDEN_VIEW.read_text(encoding="utf-8").splitlines()[3:]
    cells = _row(catalog, lines, "Forest")
    assert cells[9] == ""
    assert cells[3].startswith("Basic Land")


def test_transform_card_row(catalog: Catalog) -> None:
    lines = GOLDEN_VIEW.read_text(encoding="utf-8").splitlines()[3:]
    cells = _row(catalog, lines, "Desperate Farmer // Depraved Harvester")
    assert cells[3].count(" // ") == 1
    assert cells[9].count(" // ") == 1


def test_quick_study_sums_two_printings(catalog: Catalog) -> None:
    lines = GOLDEN_VIEW.read_text(encoding="utf-8").splitlines()[3:]
    cells = _row(catalog, lines, "Quick Study")
    assert cells[8] == "fdn,sos"
    assert cells[1] == "2"


def test_banned_and_game_changer_row(catalog: Catalog) -> None:
    collection = read_collection(GOLDEN)
    banned = catalog.card("Wick, the Whorled Mind")
    assert banned is not None
    variant_card = Card(
        name=banned.name,
        oracle_id=banned.oracle_id,
        layout=banned.layout,
        type_line=banned.type_line,
        mana_cost=banned.mana_cost,
        cmc=banned.cmc,
        colors=banned.colors,
        color_identity=banned.color_identity,
        produced_mana=banned.produced_mana,
        oracle_text=banned.oracle_text,
        keywords=banned.keywords,
        legality="banned",
        game_changer=True,
        edhrec_rank=banned.edhrec_rank,
        faces=banned.faces,
        tokens=banned.tokens,
        printings=banned.printings,
    )
    other_cards = tuple(card for card in catalog.cards if card.name != banned.name)
    variant_catalog = Catalog(catalog.refreshed, (*other_cards, variant_card), catalog.tokens)
    text = render(collection, variant_catalog)
    lines = text.splitlines()[3:]
    cells = _row(variant_catalog, lines, "Wick, the Whorled Mind")
    assert cells[5] == "banned"
    assert cells[6] == "GC"


def test_no_rank_and_fractional_cmc(catalog: Catalog) -> None:
    collection = read_collection(GOLDEN)
    forest = catalog.card("Forest")
    assert forest is not None
    variant_card = Card(
        name=forest.name,
        oracle_id=forest.oracle_id,
        layout=forest.layout,
        type_line=forest.type_line,
        mana_cost=forest.mana_cost,
        cmc=2.5,
        colors=forest.colors,
        color_identity=forest.color_identity,
        produced_mana=forest.produced_mana,
        oracle_text=forest.oracle_text,
        keywords=forest.keywords,
        legality=forest.legality,
        game_changer=forest.game_changer,
        edhrec_rank=None,
        faces=forest.faces,
        tokens=forest.tokens,
        printings=forest.printings,
    )
    other_cards = tuple(card for card in catalog.cards if card.name != forest.name)
    variant_catalog = Catalog(catalog.refreshed, (*other_cards, variant_card), catalog.tokens)
    text = render(collection, variant_catalog)
    lines = text.splitlines()[3:]
    cells = _row(variant_catalog, lines, "Forest")
    assert cells[7] == ""
    assert cells[4] == "2.5"


def test_view_build_is_deterministic(catalog: Catalog) -> None:
    collection = read_collection(GOLDEN)
    assert render(collection, catalog) == render(collection, catalog)


def test_scope_excludes_lots_and_narrows_sets(catalog: Catalog) -> None:
    collection = read_collection(GOLDEN)
    text = render(collection, catalog, exclude_binders=["OmniHive: Secrets of Strixhaven"])
    lines = text.splitlines()
    assert lines[2] == "name\tqty\tci\ttype\tcmc\tlegal\tgc\trank\tsets\ttext"
    assert len(lines) == 3
    assert "scope" in lines[0]
    assert 'exclude-binder "OmniHive: Secrets of Strixhaven"' in lines[0]


def test_token_owned_printing_ignores_same_named_card(catalog: Catalog) -> None:
    """Brief 1 B5: the join goes through each lot's printing (`Catalog.owner_of`),
    never by name alone. The fixture owns a lot whose scryfall_id is the
    Splash Lasher *token*'s own printing; a synthetic card sharing that name
    must not pick it up, and the token must not fabricate a row either."""
    collection = read_collection(GOLDEN)
    lot = next(
        lot for lot in collection.lots if lot.scryfall_id == "53065735-c427-458e-ade4-ec2d81c8d277"
    )
    assert lot.name == "Splash Lasher"
    template = catalog.card("Forest")
    assert template is not None
    decoy_card = Card(
        name="Splash Lasher",
        oracle_id=template.oracle_id,
        layout=template.layout,
        type_line=template.type_line,
        mana_cost=template.mana_cost,
        cmc=template.cmc,
        colors=template.colors,
        color_identity=template.color_identity,
        produced_mana=template.produced_mana,
        oracle_text=template.oracle_text,
        keywords=template.keywords,
        legality=template.legality,
        game_changer=template.game_changer,
        edhrec_rank=template.edhrec_rank,
        faces=template.faces,
        tokens=template.tokens,
        printings=(),
    )
    variant_catalog = Catalog(catalog.refreshed, (*catalog.cards, decoy_card), catalog.tokens)
    text = render(collection, variant_catalog)
    names = [line.split("\t")[0] for line in text.splitlines()[3:]]
    assert "Splash Lasher" not in names


def test_write_is_all_or_nothing(tmp_path: Path) -> None:
    path = tmp_path / "view.tsv"
    write("first\n", path)
    assert path.read_text(encoding="utf-8") == "first\n"
    write("second\n", path)
    assert path.read_text(encoding="utf-8") == "second\n"


def test_write_failure_is_a_tool_error(tmp_path: Path) -> None:
    path = tmp_path / "missing_dir_but_blocked" / "view.tsv"
    (tmp_path / "missing_dir_but_blocked").write_text("not a directory")
    with pytest.raises(ToolError) as caught:
        write("x\n", path)
    assert caught.value.error == "view_write_failed"
    assert "path" in caught.value.detail
