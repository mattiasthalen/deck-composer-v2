"""The catalog: fixture hygiene, the four lookups, the file against its golden,
merge, replace, and the two checks a collection must pass."""

from __future__ import annotations

import json
from dataclasses import replace as with_fields
from pathlib import Path

import pytest

from deck_composer.catalog import (
    Card,
    Catalog,
    Face,
    Printing,
    RefreshChanges,
    Token,
    merge,
    missing_printings,
    name_mismatches,
    read,
    render,
    replace,
    write,
)
from deck_composer.collection import Collection, Lot
from deck_composer.errors import ToolError
from deck_composer.scryfall import project_all
from tests.helpers import FIXTURES, GOLDEN, SCRYFALL_FIXTURE, load_scryfall_fixture

FORBIDDEN_KEYS = ("prices", "purchase_uris", "image_uris")

CATALOG_GOLDEN = FIXTURES / "golden" / "manabox_base.catalog.json"
EMPTY = Catalog(refreshed=None, cards=(), tokens=())

# Identities read from the Scryfall fixture, named here so the criteria read.
WICK = "Wick, the Whorled Mind"
WICK_PRINTING = "29089810-d7fb-4abe-b729-bfabed6aed2b"
SNAIL_ORACLE = "50c2fc3e-dc2d-43c4-b2e5-d0d72889e61b"
SNAIL_PRINTING = "d9bb0a91-b73e-465b-8c0e-50fc28e66fda"
# "Rust-Shield Rampager" and "Splash Lasher" are the identity edge of Brief 4:
# a name carried by both a card and a token, and a name carried by a token only.
RAMPAGER = "Rust-Shield Rampager"
RAMPAGER_TOKEN_ORACLE = "93793ab5-3c85-4c78-95c2-c228e39bd930"
SPLASH_LASHER_ORACLE = "1ba44387-3576-428a-8211-ee083a064ad2"


def _walk(obj: object) -> list[str]:
    """Every dict key anywhere in a nested structure."""
    keys: list[str] = []
    if isinstance(obj, dict):
        keys.extend(obj.keys())
        for value in obj.values():
            keys.extend(_walk(value))
    elif isinstance(obj, list):
        for item in obj:
            keys.extend(_walk(item))
    return keys


# --- AC-74: no price or purchase-link key anywhere under tests/fixtures/scryfall/ --


def test_fixtures_scryfall_carry_no_price_or_purchase_keys() -> None:
    scryfall_dir = FIXTURES / "scryfall"
    files = sorted(scryfall_dir.glob("*.json"))
    assert files, "expected at least one fixture under tests/fixtures/scryfall/"
    for path in files:
        body = json.loads(path.read_text(encoding="utf-8"))
        keys = set(_walk(body))
        for forbidden in FORBIDDEN_KEYS:
            assert forbidden not in keys, f"{path.name} carries {forbidden!r}"


# --- AC-80: the fixture holds every base-golden printing and their tokens, nothing else --


def test_scryfall_fixture_covers_exactly_the_golden_printings_and_their_tokens() -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    golden_ids = {lot["scryfall_id"] for lot in golden["lots"]}

    body = json.loads(SCRYFALL_FIXTURE.read_text(encoding="utf-8"))
    objects = body["data"]
    assert body["not_found"] == []

    fetched_ids = {obj["id"] for obj in objects}
    assert golden_ids <= fetched_ids, "every golden printing must be in the fixture"

    # Only tokens listed by the *card* objects (the 25 golden printings) are
    # fetched; a token's own all_parts is not followed further (WP0 brief).
    golden_objects = [obj for obj in objects if obj["id"] in golden_ids]
    token_ids = {
        part["id"]
        for obj in golden_objects
        for part in (obj.get("all_parts") or [])
        if part.get("component") == "token"
    }
    assert token_ids <= fetched_ids, "every related token must be in the fixture"

    # Nothing else: every fetched object is either a golden printing or a related token.
    assert fetched_ids == golden_ids | token_ids


def test_scryfall_fixture_holds_the_named_cards_and_tokens() -> None:
    objects = load_scryfall_fixture()
    names = {obj["name"] for obj in objects}
    layouts = {obj["name"]: obj["layout"] for obj in objects}

    assert "Desperate Farmer // Depraved Harvester" in names
    assert layouts["Desperate Farmer // Depraved Harvester"] == "transform"

    assert "Honorbound Page // Forum's Favor" in names
    assert layouts["Honorbound Page // Forum's Favor"] == "prepare"

    assert layouts["Splash Lasher"] == "token"
    splash_lasher = next(obj for obj in objects if obj["name"] == "Splash Lasher")
    assert splash_lasher["set"] == "tblb"

    assert "Wick, the Whorled Mind" in names
    assert "Snail" in names

    quick_studies = [obj for obj in objects if obj["name"] == "Quick Study"]
    assert len(quick_studies) == 2
    assert {obj["set"] for obj in quick_studies} == {"fdn", "sos"}


# --- Catalog lookups, built from hand-made records ------------------------------


def _printing(scryfall_id: str) -> Printing:
    return Printing(
        scryfall_id=scryfall_id,
        set="blb",
        set_type="expansion",
        collector_number="1",
        rarity="common",
        released_at="2024-08-02",
    )


def _card(name: str, oracle_id: str, *, faces: tuple[Face, ...] | None = None) -> Card:
    return Card(
        name=name,
        oracle_id=oracle_id,
        layout="normal" if faces is None else "transform",
        type_line="Creature",
        mana_cost="{1}",
        cmc=1,
        colors=("B",),
        color_identity=("B",),
        produced_mana=None,
        oracle_text=None,
        keywords=(),
        legality="legal",
        game_changer=False,
        edhrec_rank=None,
        faces=faces,
        tokens=("token-oracle-1",),
        printings=(_printing(f"printing-{oracle_id}"),),
    )


def _token(oracle_id: str, name: str) -> Token:
    return Token(
        oracle_id=oracle_id,
        name=name,
        layout="token",
        type_line="Token Creature",
        oracle_text="",
        printings=(_printing(f"token-printing-{oracle_id}"),),
    )


def _build_catalog() -> Catalog:
    front = Face(name="Front", mana_cost="{1}", type_line="Creature", colors=("B",), oracle_text="")
    back = Face(name="Back", mana_cost=None, type_line="Creature", colors=None, oracle_text=None)
    two_faced = _card("Front // Back", "oracle-front-back", faces=(front, back))
    wick = _card("Wick, the Whorled Mind", "oracle-wick")
    return Catalog(
        refreshed=None,
        cards=(two_faced, wick),
        tokens=(_token("token-oracle-1", "Snail"),),
    )


def test_card_looks_up_by_exact_name() -> None:
    catalog = _build_catalog()
    assert catalog.card("Wick, the Whorled Mind") is not None
    assert catalog.card("wick, the whorled mind") is None
    assert catalog.card("Snail") is None


def test_token_looks_up_by_oracle_id() -> None:
    catalog = _build_catalog()
    token = catalog.token("token-oracle-1")
    assert token is not None
    assert token.name == "Snail"
    assert catalog.token("does-not-exist") is None


def test_owner_of_finds_card_or_token_printing() -> None:
    catalog = _build_catalog()
    assert catalog.owner_of("printing-oracle-wick") is catalog.card("Wick, the Whorled Mind")
    assert catalog.owner_of("token-printing-token-oracle-1") is catalog.token("token-oracle-1")
    assert catalog.owner_of("nowhere") is None


def test_resolve_is_case_insensitive_and_full_name_beats_face_name() -> None:
    catalog = _build_catalog()
    assert catalog.resolve("wick, the whorled mind") is catalog.card("Wick, the Whorled Mind")
    assert catalog.resolve("front") is catalog.card("Front // Back")
    assert catalog.resolve("BACK") is catalog.card("Front // Back")
    assert catalog.resolve("Sol Ring") is None


def test_resolve_full_name_match_wins_over_face_name_match() -> None:
    # A card literally named "Back" would win resolution of "back" over the
    # two-faced card whose back face happens to be named "Back".
    catalog = _build_catalog()
    named_back = _card("Back", "oracle-back-alone")
    catalog = Catalog(
        refreshed=None,
        cards=(*catalog.cards, named_back),
        tokens=catalog.tokens,
    )
    assert catalog.resolve("back") is catalog.card("Back")


def test_catalog_sorts_cards_by_name_and_tokens_by_oracle_id() -> None:
    catalog = Catalog(
        refreshed=None,
        cards=(_card("Zeta", "oracle-z"), _card("Alpha", "oracle-a")),
        tokens=(_token("z", "Z"), _token("a", "A")),
    )
    assert [card.name for card in catalog.cards] == ["Alpha", "Zeta"]
    assert [token.oracle_id for token in catalog.tokens] == ["a", "z"]


def test_records_round_trip_to_dict() -> None:
    catalog = _build_catalog()
    front_back = catalog.card("Front // Back")
    assert front_back is not None
    body = front_back.to_dict()
    assert body["faces"][0]["name"] == "Front"
    assert body["faces"][1]["colors"] is None

    snail = catalog.token("token-oracle-1")
    assert snail is not None
    assert snail.to_dict()["name"] == "Snail"


# --- the file: AC-21 to AC-26 --------------------------------------------------


def _from_fixture() -> Catalog:
    """The catalog the Scryfall fixture builds: project every object, merge into
    an empty catalog. The golden is this, rendered."""
    return merge(EMPTY, project_all(load_scryfall_fixture()))


def _golden() -> Catalog:
    return read(CATALOG_GOLDEN)


def test_fixture_catalog_matches_golden_byte_for_byte(tmp_path: Path) -> None:
    out = tmp_path / "catalog.json"
    write(_from_fixture(), out)
    assert out.read_bytes() == CATALOG_GOLDEN.read_bytes()


def test_golden_layout_is_one_entry_per_line_utf8_lf_and_sorted() -> None:
    raw = CATALOG_GOLDEN.read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"}\n")
    assert "—" in raw.decode("utf-8"), "non-ASCII is written verbatim"
    body = json.loads(raw.decode("utf-8"))
    assert list(body) == ["schema", "refreshed", "cards", "tokens"]
    assert body["schema"] == 1
    assert body["refreshed"] is None
    assert [card["name"] for card in body["cards"]] == sorted(
        card["name"] for card in body["cards"]
    )
    assert [token["oracle_id"] for token in body["tokens"]] == sorted(
        token["oracle_id"] for token in body["tokens"]
    )
    first_card = body["cards"][0]
    assert list(first_card)[:4] == ["name", "oracle_id", "layout", "type_line"]
    assert list(body["tokens"][0]) == [
        "oracle_id",
        "name",
        "layout",
        "type_line",
        "oracle_text",
        "printings",
    ]
    for entry in body["cards"] + body["tokens"]:
        assert entry["printings"]
        ids = [printing["scryfall_id"] for printing in entry["printings"]]
        assert ids == sorted(ids)


def test_insertion_order_does_not_change_the_bytes() -> None:
    records = project_all(load_scryfall_fixture())
    forwards = render(merge(EMPTY, records))
    backwards = render(merge(EMPTY, list(reversed(records))))
    assert forwards == backwards == CATALOG_GOLDEN.read_text(encoding="utf-8")

    catalog = _golden()
    shuffled = Catalog(
        refreshed=catalog.refreshed,
        cards=tuple(reversed(catalog.cards)),
        tokens=tuple(reversed(catalog.tokens)),
    )
    assert render(shuffled) == forwards


def test_golden_round_trips_byte_for_byte(tmp_path: Path) -> None:
    out = tmp_path / "catalog.json"
    write(_golden(), out)
    assert out.read_bytes() == CATALOG_GOLDEN.read_bytes()


def test_read_fails_on_an_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text('{"schema": 2, "cards": [], "tokens": []}', encoding="utf-8")
    with pytest.raises(ToolError) as caught:
        read(path)
    assert caught.value.error == "catalog_schema_unknown"
    assert caught.value.detail["schema"] == 2
    assert "enrich" in caught.value.next_step


def test_read_fails_on_an_absent_file(tmp_path: Path) -> None:
    with pytest.raises(ToolError) as caught:
        read(tmp_path / "catalog.json")
    assert caught.value.error == "catalog_not_found"
    assert "enrich" in caught.value.next_step


@pytest.mark.parametrize(
    "text",
    ["", "not json", "[1]", '{"schema": 1}', '{"schema": 1, "cards": []}'],
)
def test_read_fails_on_a_broken_file(tmp_path: Path, text: str) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ToolError) as caught:
        read(path)
    assert caught.value.error == "catalog_unreadable"
    assert caught.value.detail["path"] == str(path)
    assert caught.value.next_step


def test_read_fails_on_a_malformed_entry(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text('{"schema": 1, "cards": [1], "tokens": []}', encoding="utf-8")
    with pytest.raises(ToolError) as caught:
        read(path)
    assert caught.value.error == "catalog_unreadable"


def test_read_ignores_unknown_keys_and_a_rewrite_drops_them(tmp_path: Path) -> None:
    body = json.loads(CATALOG_GOLDEN.read_text(encoding="utf-8"))
    body["summoned_by"] = "a hand edit"
    body["cards"][0]["price"] = "never"
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "rewritten.json"
    write(read(path), out)
    assert out.read_bytes() == CATALOG_GOLDEN.read_bytes()


def test_write_failure_is_a_tool_error(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    with pytest.raises(ToolError) as caught:
        write(EMPTY, blocked / "catalog.json")
    assert caught.value.error == "catalog_write_failed"
    assert caught.value.next_step


# --- the golden's lookups and invariants: AC-27 to AC-30 -----------------------


def test_lookups_over_the_golden() -> None:
    catalog = _golden()
    wick = catalog.card(WICK)
    assert wick is not None
    assert wick.oracle_id == "5af729e8-8a40-4991-8270-612e377451de"

    # A name carried by a card and by a token answers with the card.
    rampager = catalog.card(RAMPAGER)
    assert rampager is not None
    assert rampager.layout == "normal"
    assert catalog.token(RAMPAGER_TOKEN_ORACLE) is not None
    assert catalog.token(RAMPAGER_TOKEN_ORACLE) is not rampager

    snail = catalog.token(SNAIL_ORACLE)
    assert snail is not None
    assert snail.name == "Snail"
    assert catalog.owner_of(SNAIL_PRINTING) is snail
    assert catalog.owner_of(WICK_PRINTING) is wick

    # A token name is never a card name.
    assert catalog.card("Snail") is None
    assert catalog.card("Splash Lasher") is None
    assert catalog.token(SPLASH_LASHER_ORACLE) is not None


def test_resolve_over_the_golden() -> None:
    catalog = _golden()
    assert catalog.resolve("wick, the whorled mind") is catalog.card(WICK)
    farmer = catalog.card("Desperate Farmer // Depraved Harvester")
    assert catalog.resolve("Desperate Farmer") is farmer
    assert catalog.resolve("Depraved Harvester") is farmer
    assert catalog.resolve("Sol Ring") is None


def test_golden_holds_the_catalog_invariants() -> None:
    catalog = _golden()
    names = [card.name for card in catalog.cards]
    assert len(names) == len(set(names))

    owners: dict[str, object] = {}
    for entry in (*catalog.cards, *catalog.tokens):
        for printing in entry.printings:
            assert printing.scryfall_id not in owners, printing.scryfall_id
            owners[printing.scryfall_id] = entry

    for card in catalog.cards:
        for oracle_id in card.tokens:
            assert catalog.token(oracle_id) is not None, oracle_id
        if card.edhrec_rank is not None:
            assert len(str(card.edhrec_rank).rstrip("0")) <= 2, card.edhrec_rank


def test_golden_carries_no_legality_outside_the_four_values_and_no_token_facts() -> None:
    body = json.loads(CATALOG_GOLDEN.read_text(encoding="utf-8"))
    for card in body["cards"]:
        assert card["legality"] in {"legal", "not_legal", "banned", "restricted"}
    for token in body["tokens"]:
        assert "legality" not in token
        assert "colors" not in token
        assert "edhrec_rank" not in token
    assert "price" not in CATALOG_GOLDEN.read_text(encoding="utf-8").lower()


# --- merge, R9 ------------------------------------------------------------------


def test_merge_adds_new_cards_and_tokens_sorted() -> None:
    merged = merge(_build_catalog(), [_card("Alpha", "oracle-alpha"), _token("z-oracle", "Zed")])
    assert merged.cards[0].name == "Alpha"
    assert merged.card("Alpha") is not None
    assert merged.token("z-oracle") is not None
    assert len(merged.tokens) == 2


def test_merge_appends_an_unseen_printing_and_alters_nothing_else() -> None:
    catalog = _build_catalog()
    before = catalog.card(WICK)
    assert before is not None
    fetched = with_fields(
        before,
        legality="banned",
        edhrec_rank=100,
        printings=(_printing("a-second-printing"),),
    )
    after = merge(catalog, [fetched]).card(WICK)
    assert after is not None
    assert after.legality == "legal"
    assert after.edhrec_rank is None
    assert [printing.scryfall_id for printing in after.printings] == [
        "a-second-printing",
        "printing-oracle-wick",
    ]


def test_merge_of_a_printing_already_listed_changes_nothing() -> None:
    catalog = _build_catalog()
    once = merge(catalog, project_all([]))
    assert render(once) == render(catalog)
    wick = catalog.card(WICK)
    assert wick is not None
    assert render(merge(catalog, [wick])) == render(catalog)


def test_merge_never_gives_a_listed_printing_to_a_second_entry() -> None:
    catalog = _build_catalog()
    intruder = with_fields(
        _card("Intruder", "oracle-intruder"),
        printings=(_printing("printing-oracle-wick"), _printing("its-own-printing")),
    )
    merged = merge(catalog, [intruder])
    added = merged.card("Intruder")
    assert added is not None
    assert [printing.scryfall_id for printing in added.printings] == ["its-own-printing"]
    assert merged.owner_of("printing-oracle-wick") is merged.card(WICK)


def test_merge_keeps_a_new_entrys_only_printing_even_when_it_is_listed() -> None:
    # An entry without a printing cannot exist, so the rename case keeps it and
    # surfaces as a name mismatch against the collection instead (R3).
    catalog = _build_catalog()
    renamed = with_fields(
        _card("Wick, the Whirled Mind", "oracle-wick-new"),
        printings=(_printing("printing-oracle-wick"),),
    )
    merged = merge(catalog, [renamed])
    entry = merged.card("Wick, the Whirled Mind")
    assert entry is not None
    assert [printing.scryfall_id for printing in entry.printings] == ["printing-oracle-wick"]


def test_merge_keeps_the_refresh_date() -> None:
    catalog = Catalog(refreshed="2026-09-14", cards=(), tokens=())
    assert merge(catalog, [_card("Alpha", "oracle-alpha")]).refreshed == "2026-09-14"


def test_merge_fails_when_one_name_carries_two_oracle_ids() -> None:
    catalog = _build_catalog()
    twin = _card(WICK, "another-oracle")
    with pytest.raises(ToolError) as caught:
        merge(catalog, [twin])
    assert caught.value.error == "name_collision"
    assert caught.value.detail["name"] == WICK
    assert set(caught.value.detail["oracle_ids"]) == {"oracle-wick", "another-oracle"}
    assert caught.value.next_step


def test_merge_folds_two_printings_of_one_card_from_one_batch() -> None:
    first = _card("Quick Study", "oracle-quick")
    second = with_fields(first, printings=(_printing("second-printing"),))
    merged = merge(EMPTY, [first, second])
    entry = merged.card("Quick Study")
    assert entry is not None
    assert len(entry.printings) == 2


# --- replace, R10 ---------------------------------------------------------------


def _refreshed(catalog: Catalog, fetched: list[Card | Token]) -> tuple[Catalog, RefreshChanges]:
    return replace(catalog, fetched, "2026-09-14")


def test_replace_sets_the_date_and_reports_nothing_when_nothing_moved() -> None:
    catalog = _build_catalog()
    after, changes = _refreshed(catalog, [*catalog.cards, *catalog.tokens])
    assert after.refreshed == "2026-09-14"
    assert changes.is_empty
    assert changes.to_dict() == {
        "legality": [],
        "game_changer": [],
        "text": [],
        "renamed": [],
        "unresolved": [],
    }
    assert render(after) == render(
        Catalog(refreshed="2026-09-14", cards=catalog.cards, tokens=catalog.tokens)
    )


def test_replace_swaps_every_field_and_keeps_the_known_printings() -> None:
    catalog = _build_catalog()
    wick = catalog.card(WICK)
    assert wick is not None
    fetched = with_fields(
        wick,
        legality="banned",
        game_changer=True,
        oracle_text="A new ability.",
        edhrec_rank=500,
        printings=(_printing("a-second-printing"),),
    )
    after, changes = _refreshed(catalog, [fetched, *catalog.tokens, catalog.cards[0]])
    entry = after.card(WICK)
    assert entry is not None
    assert entry.legality == "banned"
    assert entry.game_changer is True
    assert entry.edhrec_rank == 500
    assert [printing.scryfall_id for printing in entry.printings] == [
        "a-second-printing",
        "printing-oracle-wick",
    ]
    assert changes.legality == ((WICK, "legal", "banned"),)
    assert changes.game_changer == ((WICK, False, True),)
    assert changes.text == (WICK,)
    assert changes.unresolved == ()
    assert changes.to_dict()["legality"] == [{"name": WICK, "from": "legal", "to": "banned"}]
    assert changes.to_dict()["game_changer"] == [{"name": WICK, "from": False, "to": True}]


def test_replace_reports_a_face_text_change() -> None:
    catalog = _build_catalog()
    two_faced = catalog.card("Front // Back")
    assert two_faced is not None
    assert two_faced.faces is not None
    faces = (with_fields(two_faced.faces[0], oracle_text="Reworded."), two_faced.faces[1])
    after, changes = _refreshed(catalog, [with_fields(two_faced, faces=faces)])
    assert changes.text == ("Front // Back",)
    entry = after.card("Front // Back")
    assert entry is not None
    assert entry.faces is not None
    assert entry.faces[0].oracle_text == "Reworded."


def test_replace_matches_a_rename_by_oracle_id() -> None:
    catalog = _build_catalog()
    wick = catalog.card(WICK)
    assert wick is not None
    after, changes = _refreshed(catalog, [with_fields(wick, name="Wick, the Whirled Mind")])
    assert changes.renamed == ((WICK, "Wick, the Whirled Mind"),)
    assert after.card(WICK) is None
    renamed = after.card("Wick, the Whirled Mind")
    assert renamed is not None
    assert renamed.oracle_id == "oracle-wick"
    assert len(after.cards) == len(catalog.cards)


def test_replace_keeps_an_entry_scryfall_did_not_return_and_names_it() -> None:
    catalog = _build_catalog()
    wick = catalog.card(WICK)
    assert wick is not None
    after, changes = _refreshed(catalog, [wick])
    assert changes.unresolved == ("Front // Back", "Snail")
    assert after.card("Front // Back") == catalog.card("Front // Back")
    assert len(after.tokens) == 1
    assert not changes.is_empty


def test_replace_adds_an_entry_the_catalog_did_not_have() -> None:
    catalog = _build_catalog()
    after, _ = _refreshed(catalog, [*catalog.cards, *catalog.tokens, _card("Alpha", "oracle-a")])
    assert after.card("Alpha") is not None


def test_replace_fails_when_a_rename_collides_with_another_name() -> None:
    catalog = _build_catalog()
    wick = catalog.card(WICK)
    assert wick is not None
    with pytest.raises(ToolError) as caught:
        _refreshed(catalog, [with_fields(wick, name="Front // Back")])
    assert caught.value.error == "name_collision"
    assert caught.value.detail["name"] == "Front // Back"


def test_replace_over_the_golden_changes_only_the_date() -> None:
    catalog = _golden()
    records: list[Card | Token] = [*catalog.cards, *catalog.tokens]
    after, changes = _refreshed(catalog, records)
    assert changes.is_empty
    assert changes.unresolved == ()
    assert render(after) == render(catalog).replace(
        '"refreshed": null', '"refreshed": "2026-09-14"'
    )


# --- coverage and name authority: R4 and R3 -------------------------------------


def _lot(name: str, scryfall_id: str, quantity: int = 1) -> Lot:
    return Lot(
        name=name,
        set_code="blb",
        collector_number="1",
        scryfall_id=scryfall_id,
        quantity=quantity,
        foil="normal",
        condition="near_mint",
        language="en",
        binder_name="A binder",
        binder_type="binder",
        added=None,
    )


def _collection(*lots: Lot) -> Collection:
    return Collection(collection_hash="sha256:" + "0" * 64, source_file="export.csv", lots=lots)


def test_missing_printings_lists_every_uncovered_lot() -> None:
    catalog = _build_catalog()
    collection = _collection(
        _lot(WICK, "printing-oracle-wick"),
        _lot("Snail", "token-printing-token-oracle-1"),
        _lot("Sol Ring", "not-in-the-catalog"),
    )
    missing = missing_printings(catalog, collection)
    assert [lot.scryfall_id for lot in missing] == ["not-in-the-catalog"]
    assert missing_printings(EMPTY, collection) == collection.lots
    assert missing_printings(catalog, _collection()) == ()


def test_name_mismatches_pairs_the_lot_with_the_catalog_name() -> None:
    catalog = _build_catalog()
    collection = _collection(
        _lot(WICK, "printing-oracle-wick"),
        _lot("Wick, The Whorled Mind", "printing-oracle-front-back"),
        _lot("Sol Ring", "not-in-the-catalog"),
    )
    mismatches = name_mismatches(catalog, collection)
    assert len(mismatches) == 1
    lot, catalog_name = mismatches[0]
    assert lot.name == "Wick, The Whorled Mind"
    assert catalog_name == "Front // Back"


def test_name_mismatches_accepts_a_lot_of_a_token_printing() -> None:
    catalog = _build_catalog()
    collection = _collection(_lot("Snail", "token-printing-token-oracle-1"))
    assert name_mismatches(catalog, collection) == ()


def test_the_golden_covers_the_base_collection_and_agrees_on_every_name() -> None:
    catalog = _golden()
    body = json.loads(GOLDEN.read_text(encoding="utf-8"))
    collection = _collection(
        *(_lot(lot["name"], lot["scryfall_id"], lot["quantity"]) for lot in body["lots"])
    )
    assert missing_printings(catalog, collection) == ()
    assert name_mismatches(catalog, collection) == ()


def test_merge_never_moves_a_printing_between_existing_entries() -> None:
    catalog = _build_catalog()
    wick = catalog.card(WICK)
    assert wick is not None
    # The two-faced card comes back carrying Wick's printing: it stays Wick's.
    two_faced = catalog.card("Front // Back")
    assert two_faced is not None
    merged = merge(catalog, [with_fields(two_faced, printings=wick.printings)])
    entry = merged.card("Front // Back")
    assert entry is not None
    assert [printing.scryfall_id for printing in entry.printings] == ["printing-oracle-front-back"]
    assert merged.owner_of("printing-oracle-wick") is merged.card(WICK)
