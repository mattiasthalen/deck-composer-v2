"""The Scryfall client and projection: batching, spacing, headers, the closed
vocabularies, the projected fields and every failure class. No test here reaches
the network except the one marked `live`."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from deck_composer.catalog import Card, Token
from deck_composer.errors import ToolError
from deck_composer.scryfall import (
    CARD_LAYOUTS,
    LEGALITIES,
    TOKEN_LAYOUTS,
    Client,
    project,
    project_all,
    related_token_ids,
)
from tests.helpers import FakeTransport, load_scryfall_fixture, recording_sleep

FIXTURE = load_scryfall_fixture()
WICK_ID = "29089810-d7fb-4abe-b729-bfabed6aed2b"
# R7's required fields for a card object, checked against the live API by the
# one test that reaches it.
REQUIRED = (
    "id",
    "oracle_id",
    "name",
    "layout",
    "type_line",
    "cmc",
    "color_identity",
    "keywords",
    "game_changer",
    "set",
    "set_type",
    "collector_number",
    "rarity",
    "released_at",
)


def obj(name: str) -> dict[str, Any]:
    """A fresh copy of one fixture object, safe to mutate."""
    return deepcopy(next(entry for entry in FIXTURE if entry["name"] == name))


def variant(name: str, /, **changes: Any) -> dict[str, Any]:
    """One fixture object with fields replaced; a value of None drops the field."""
    entry = obj(name)
    for field, value in changes.items():
        if value is None:
            entry.pop(field, None)
        else:
            entry[field] = value
    return entry


def card(name: str) -> Card:
    record = project(obj(name))
    assert isinstance(record, Card)
    return record


def failure(record: dict[str, Any]) -> ToolError:
    with pytest.raises(ToolError) as caught:
        project(record)
    return caught.value


def client(transport: FakeTransport) -> tuple[Client, Any]:
    """A client on the fake transport, with the recording sleep it spaces its
    requests by. The sleep carries every duration on `durations`."""
    sleep: Any = recording_sleep()
    return Client(transport=transport, sleep=sleep, version="0.1.0"), sleep


def bodies(transport: FakeTransport) -> list[dict[str, Any]]:
    return [json.loads(body.decode("utf-8")) for _, _, _, body in transport.calls if body]


# --- the client -------------------------------------------------------------


def test_hundred_identifiers_are_two_batches_of_seventy_five_and_twenty_five() -> None:
    transport = FakeTransport(FIXTURE)
    scryfall, _ = client(transport)
    identifiers = [{"id": f"00000000-0000-0000-0000-{index:012d}"} for index in range(100)]

    data, not_found = scryfall.collection(identifiers)

    assert [method for method, _, _, _ in transport.calls] == ["POST", "POST"]
    assert all(url.endswith("/cards/collection") for _, url, _, _ in transport.calls)
    assert [len(body["identifiers"]) for body in bodies(transport)] == [75, 25]
    assert data == []
    assert len(not_found) == 100
    assert scryfall.requests == 2


def test_no_identifiers_make_no_request() -> None:
    transport = FakeTransport(FIXTURE)
    scryfall, _ = client(transport)

    assert scryfall.collection([]) == ([], [])
    assert transport.calls == []
    assert scryfall.requests == 0


def test_collection_answers_the_objects_found_and_the_identifiers_missed() -> None:
    transport = FakeTransport(FIXTURE)
    scryfall, _ = client(transport)

    data, not_found = scryfall.collection([{"id": WICK_ID}, {"id": "no-such-printing"}])

    assert [entry["name"] for entry in data] == ["Wick, the Whorled Mind"]
    assert not_found == [{"id": "no-such-printing"}]


def test_every_request_identifies_the_tool() -> None:
    transport = FakeTransport(FIXTURE, fuzzy={"Sol Rng": obj("Plains")})
    scryfall, _ = client(transport)

    scryfall.collection([{"id": WICK_ID}])
    scryfall.fuzzy("Sol Rng")

    assert len(transport.calls) == 2
    for _, _, headers, _ in transport.calls:
        assert headers["Accept"] == "application/json"
        assert "deck-composer" in headers["User-Agent"]
        assert "https://github.com/mattiasthalen/deck-composer-v2" in headers["User-Agent"]
    assert transport.calls[0][2]["Content-Type"] == "application/json"


def test_requests_are_spaced_and_never_overlap() -> None:
    transport = FakeTransport(FIXTURE)
    seen: list[tuple[int, float]] = []

    def sleep(seconds: float) -> None:
        seen.append((len(transport.calls), seconds))

    scryfall = Client(transport=transport, sleep=sleep, version="0.1.0")
    for _ in range(3):
        scryfall.collection([{"id": WICK_ID}])
    scryfall.fuzzy("Wick")

    # One sleep of at least 0.1 s between each pair, none before the first, and
    # each one after a completed request: the calls never overlap.
    assert seen == [(1, 0.1), (2, 0.1), (3, 0.1)]
    assert scryfall.requests == 4


def test_fuzzy_answers_a_name_or_nothing() -> None:
    transport = FakeTransport(FIXTURE, fuzzy={"Sol Rng": obj("Plains")})
    scryfall, _ = client(transport)

    assert scryfall.fuzzy("Sol Rng") == "Plains"
    assert scryfall.fuzzy("Nonsense") is None
    assert scryfall.requests == 2
    assert all(method == "GET" for method, _, _, _ in transport.calls)
    assert "fuzzy=Sol+Rng" in transport.calls[0][1]


def test_transport_failure_is_unreachable() -> None:
    transport = FakeTransport(FIXTURE, fail_with=ConnectionError("no route to host"))
    scryfall, _ = client(transport)

    with pytest.raises(ToolError) as caught:
        scryfall.collection([{"id": WICK_ID}])

    assert caught.value.error == "scryfall_unreachable"
    assert caught.value.next_step
    assert len(transport.calls) == 1


def test_server_status_is_a_scryfall_error() -> None:
    transport = FakeTransport(FIXTURE, status=500)
    scryfall, _ = client(transport)

    with pytest.raises(ToolError) as caught:
        scryfall.collection([{"id": WICK_ID}])

    assert caught.value.error == "scryfall_error"
    assert caught.value.detail["status"] == 500


def test_a_rate_limit_is_retried_once_and_then_reported() -> None:
    transport = FakeTransport(FIXTURE, status=429)
    scryfall, sleep = client(transport)

    with pytest.raises(ToolError) as caught:
        scryfall.collection([{"id": WICK_ID}])

    assert caught.value.error == "scryfall_error"
    assert caught.value.detail["status"] == 429
    assert len(transport.calls) == 2
    assert sleep.durations == [0.1]


def test_a_status_that_is_not_retryable_is_reported_at_once() -> None:
    transport = FakeTransport(FIXTURE, status=403)
    scryfall, _ = client(transport)

    with pytest.raises(ToolError) as caught:
        scryfall.collection([{"id": WICK_ID}])

    assert caught.value.detail["status"] == 403
    assert len(transport.calls) == 1


def test_a_body_that_is_not_an_object_is_a_scryfall_error() -> None:
    def transport(method: str, url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
        return 200, b"[]"

    scryfall = Client(transport=transport, sleep=recording_sleep(), version="0.1.0")
    with pytest.raises(ToolError) as caught:
        scryfall.collection([{"id": WICK_ID}])

    assert caught.value.error == "scryfall_error"


def test_a_body_that_is_not_json_is_a_scryfall_error() -> None:
    def transport(method: str, url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
        return 200, b"<html>down</html>"

    scryfall = Client(transport=transport, sleep=recording_sleep(), version="0.1.0")
    with pytest.raises(ToolError) as caught:
        scryfall.collection([{"id": WICK_ID}])

    assert caught.value.error == "scryfall_error"
    assert caught.value.next_step


# --- projection -------------------------------------------------------------


def test_transform_card_keeps_its_faces() -> None:
    record = card("Desperate Farmer // Depraved Harvester")

    assert record.layout == "transform"
    assert record.mana_cost is None
    assert record.colors is None
    assert record.oracle_text is None
    assert record.color_identity == ("B",)
    assert record.faces is not None
    assert [face.name for face in record.faces] == ["Desperate Farmer", "Depraved Harvester"]
    assert [face.mana_cost for face in record.faces] == ["{2}{B}", ""]
    assert all(face.oracle_text for face in record.faces)
    assert record.type_line == "Creature — Human Peasant // Creature — Human Knight"


def test_prepare_card_is_a_card_with_a_card_level_mana_cost() -> None:
    record = card("Honorbound Page // Forum's Favor")

    assert record.layout == "prepare"
    assert record.mana_cost == "{3}{W} // {W}"
    assert record.faces is not None
    assert len(record.faces) == 2


def test_single_faced_card_has_no_faces() -> None:
    assert card("Wick, the Whorled Mind").faces is None


def test_token_is_classified_by_layout_and_carries_no_card_facts() -> None:
    record = project(obj("Splash Lasher"))

    assert isinstance(record, Token)
    assert record.layout == "token"
    assert record.printings[0].set_type == "token"
    assert set(record.to_dict()) == {
        "oracle_id",
        "name",
        "layout",
        "type_line",
        "oracle_text",
        "printings",
    }


def test_every_fixture_object_projects() -> None:
    records = project_all(FIXTURE)

    assert len(records) == len(FIXTURE)
    assert {type(record) for record in records} == {Card, Token}
    for record in records:
        assert record.layout in (CARD_LAYOUTS | TOKEN_LAYOUTS)
        assert len(record.printings) == 1
        if isinstance(record, Card):
            assert record.legality in LEGALITIES


def test_unknown_layout_names_the_constant_to_extend() -> None:
    caught = failure(variant("Wick, the Whorled Mind", layout="frobnicate"))

    assert caught.error == "layout_unknown"
    assert caught.detail["layout"] == "frobnicate"
    assert caught.detail["name"] == "Wick, the Whorled Mind"
    assert caught.detail["scryfall_id"] == WICK_ID
    assert caught.detail["constant"] == "CARD_LAYOUTS or TOKEN_LAYOUTS"
    assert "CARD_LAYOUTS" in caught.next_step


def test_missing_required_field_names_the_field() -> None:
    caught = failure(variant("Wick, the Whorled Mind", color_identity=None))

    assert caught.error == "payload_invalid"
    assert caught.detail["field"] == "color_identity"
    assert caught.detail["scryfall_id"] == WICK_ID
    assert caught.next_step


def test_unknown_legality_names_the_field() -> None:
    legalities = dict(obj("Wick, the Whorled Mind")["legalities"], commander="probably")
    caught = failure(variant("Wick, the Whorled Mind", legalities=legalities))

    assert caught.error == "payload_invalid"
    assert caught.detail["field"] == "legalities.commander"


@pytest.mark.parametrize(
    "field", ["name", "type_line", "cmc", "keywords", "game_changer", "set", "released_at"]
)
def test_every_required_card_field_is_required(field: str) -> None:
    caught = failure(variant("Wick, the Whorled Mind", **{field: None}))

    assert caught.error == "payload_invalid"
    assert caught.detail["field"] == field


def test_oracle_id_is_read_from_the_faces_when_the_object_has_none() -> None:
    source = obj("Desperate Farmer // Depraved Harvester")
    oracle_id = source.pop("oracle_id")
    source["layout"] = "reversible_card"
    source["card_faces"][0]["oracle_id"] = oracle_id

    record = project(source)

    assert record.oracle_id == oracle_id
    assert record.layout == "reversible_card"


def test_oracle_id_missing_everywhere_is_payload_invalid() -> None:
    caught = failure(variant("Wick, the Whorled Mind", oracle_id=None))

    assert caught.error == "payload_invalid"
    assert caught.detail["field"] == "oracle_id"


@pytest.mark.parametrize(
    ("rank", "stored"),
    [(9518, 9500), (22870, 23000), (120, 120), (9950, 10000), (7, 7), (12345, 12000), (None, None)],
)
def test_edhrec_rank_is_two_significant_figures(rank: int | None, stored: int | None) -> None:
    assert card_rank(rank) == stored


def card_rank(rank: int | None) -> int | None:
    record = project(variant("Wick, the Whorled Mind", edhrec_rank=rank))
    assert isinstance(record, Card)
    return record.edhrec_rank


def test_prices_and_purchase_links_never_leave_the_module() -> None:
    priced = variant(
        "Wick, the Whorled Mind",
        prices={"usd": "13.37", "eur": "11.11"},
        purchase_uris={"tcgplayer": "https://example.invalid/buy"},
    )

    rendered = json.dumps(project(priced).to_dict(), ensure_ascii=False)

    assert "prices" not in rendered
    assert "purchase" not in rendered
    assert "13.37" not in rendered
    assert "example.invalid" not in rendered


def test_an_unknown_field_is_ignored() -> None:
    record = project(variant("Wick, the Whorled Mind", frobnicated_at="2026-09-14"))

    assert "frobnicated" not in json.dumps(record.to_dict())


def test_a_failure_on_a_priced_object_never_echoes_the_price() -> None:
    caught = failure(
        variant(
            "Wick, the Whorled Mind",
            layout="frobnicate",
            prices={"usd": "13.37"},
        )
    )

    assert "13.37" not in json.dumps(caught.to_dict())


# --- related tokens ---------------------------------------------------------


def test_related_token_ids_follow_token_components_only() -> None:
    wick = obj("Wick, the Whorled Mind")
    components = {part["component"] for part in wick["all_parts"]}

    assert components == {"token", "combo_piece"}
    assert related_token_ids(wick) == ("d9bb0a91-b73e-465b-8c0e-50fc28e66fda",)


def test_related_token_ids_of_an_object_without_parts() -> None:
    assert related_token_ids(obj("Plains")) == ()


def test_project_all_links_a_card_to_the_tokens_fetched_with_it() -> None:
    snail = next(
        entry for entry in FIXTURE if entry["id"] == "d9bb0a91-b73e-465b-8c0e-50fc28e66fda"
    )
    records = project_all([obj("Wick, the Whorled Mind"), snail])

    wick, token = records
    assert isinstance(wick, Card)
    assert isinstance(token, Token)
    assert wick.tokens == (token.oracle_id,)


def test_project_all_leaves_a_token_it_did_not_see_unlinked() -> None:
    records = project_all([obj("Wick, the Whorled Mind")])

    assert isinstance(records[0], Card)
    assert records[0].tokens == ()


def test_project_all_sorts_the_linked_oracle_ids() -> None:
    wick = obj("Wick, the Whorled Mind")
    tokens = [entry for entry in FIXTURE if entry["layout"] == "token"][:3]
    wick["all_parts"] = [
        {"component": "token", "id": token["id"], "name": token["name"]} for token in tokens
    ]

    records = project_all([wick, *tokens])

    assert isinstance(records[0], Card)
    assert records[0].tokens == tuple(sorted(token["oracle_id"] for token in tokens))


def test_project_leaves_the_tokens_of_a_card_empty() -> None:
    assert card("Wick, the Whorled Mind").tokens == ()


# --- the live shape ---------------------------------------------------------


@pytest.mark.live
def test_live_collection_request_matches_the_accepted_shape() -> None:
    """AC-84. Deselected by default; a failure here means Scryfall drifted."""
    scryfall = Client(version="0.1.0")

    data, not_found = scryfall.collection([{"id": WICK_ID}])

    assert not_found == []
    assert len(data) == 1
    fetched = data[0]
    assert [field for field in REQUIRED if field not in fetched] == []
    assert fetched["layout"] in (CARD_LAYOUTS | TOKEN_LAYOUTS)
    assert fetched["legalities"]["commander"] in LEGALITIES
    assert isinstance(project(fetched), Card)


# --- ADR-0008: a token set type marks a token whatever the layout ----------


def test_role_token_with_flip_layout_in_a_token_set_is_a_token() -> None:
    role = variant(
        "Wick, the Whorled Mind",
        layout="flip",
        set="twoe",
        set_type="token",
        type_line="Token Enchantment — Aura Role // Token Enchantment — Aura Role",
    )
    record = project(role)
    assert isinstance(record, Token)
    assert record.layout == "flip"
    assert record.printings[0].set_type == "token"


def test_flip_card_in_an_expansion_is_a_card() -> None:
    record = project(variant("Wick, the Whorled Mind", layout="flip"))
    assert isinstance(record, Card)
    assert record.layout == "flip"


def test_dungeon_with_normal_layout_in_a_token_set_is_a_token() -> None:
    dungeon = variant("Wick, the Whorled Mind", set="tafr", set_type="token", type_line="Dungeon")
    record = project(dungeon)
    assert isinstance(record, Token)
    assert record.type_line == "Dungeon"


def test_unknown_layout_fails_loudly_even_in_a_token_set() -> None:
    with pytest.raises(ToolError) as caught:
        project(variant("Wick, the Whorled Mind", layout="frobnicate", set_type="token"))
    assert caught.value.error == "layout_unknown"
