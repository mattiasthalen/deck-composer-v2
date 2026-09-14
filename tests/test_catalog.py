"""Catalog records: hygiene of the Scryfall fixture, the four Catalog lookups."""

from __future__ import annotations

import json

from deck_composer.catalog import Card, Catalog, Face, Printing, Token
from tests.helpers import FIXTURES, GOLDEN, SCRYFALL_FIXTURE, load_scryfall_fixture

FORBIDDEN_KEYS = ("prices", "purchase_uris", "image_uris")


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
