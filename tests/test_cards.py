"""The three operations: what they fetch, what they write, what they report.

Every test injects a fake transport through the client; nothing reaches the
network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import replace as with_fields
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from deck_composer import cards
from deck_composer.catalog import Catalog
from deck_composer.catalog import read as read_catalog
from deck_composer.catalog import write as write_catalog
from deck_composer.collection import Collection, Lot
from deck_composer.collection import read as read_collection
from deck_composer.collection import write as write_collection
from deck_composer.errors import ToolError
from deck_composer.scryfall import Client
from tests.helpers import FIXTURES, GOLDEN, FakeTransport, load_scryfall_fixture, recording_sleep

CATALOG_GOLDEN = FIXTURES / "golden" / "manabox_base.catalog.json"
VIEW_GOLDEN = FIXTURES / "golden" / "manabox_base.view.tsv"

BINDER = "OmniHive: Secrets of Strixhaven"
WICK = "Wick, the Whorled Mind"
FARMER = "Desperate Farmer // Depraved Harvester"
COLOSSUS = "Arbor Colossus"
SNAIL_ORACLE = "50c2fc3e-dc2d-43c4-b2e5-d0d72889e61b"
FOREST_PRINTING = "d232fcc2-12f6-401a-b1aa-ddff11cb9378"

# Identities for the objects the tests synthesize from the fixture.
RING_ID = "00000000-0000-4000-8000-000000000001"
RING_ORACLE = "00000000-0000-4000-8000-000000000002"
SECOND_WICK_ID = "00000000-0000-4000-8000-000000000003"
UNKNOWN_ID = "00000000-0000-4000-8000-000000000004"


# --- the tree the operations run against --------------------------------------


@dataclass(frozen=True, slots=True)
class Paths:
    collection: Path
    catalog: Path
    view: Path


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    """The base collection beside an empty directory for the two derived files."""
    collection = tmp_path / "collection.json"
    collection.write_bytes(GOLDEN.read_bytes())
    return Paths(collection, tmp_path / "catalog.json", tmp_path / "view.tsv")


def fake(objects: list[dict[str, Any]] | None = None, **options: Any) -> Client:
    transport = FakeTransport(load_scryfall_fixture() if objects is None else objects, **options)
    return Client(transport=transport, sleep=recording_sleep(), version="test")


def transport_of(client: Client) -> FakeTransport:
    """The transport the test injected, for the requests it recorded."""
    transport = client._transport
    assert isinstance(transport, FakeTransport)
    return transport


def find(objects: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(obj for obj in objects if obj["name"] == name)


def without(objects: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [obj for obj in objects if obj["name"] != name]


def changed(entry: str, **fields: Any) -> list[dict[str, Any]]:
    """The fixture with one object's fields replaced."""
    objects = load_scryfall_fixture()
    find(objects, entry).update(fields)
    return objects


def sol_ring() -> dict[str, Any]:
    """A card the fixture does not carry, built from one that it does."""
    obj = dict(find(load_scryfall_fixture(), "Thrill of Possibility"))
    obj.pop("all_parts", None)
    obj.update(
        {
            "id": RING_ID,
            "oracle_id": RING_ORACLE,
            "name": "Sol Ring",
            "mana_cost": "{1}",
            "cmc": 1,
            "colors": [],
            "color_identity": [],
            "type_line": "Artifact",
            "oracle_text": "{T}: Add {C}{C}.",
            "keywords": [],
            "edhrec_rank": 1,
            "set": "fdn",
            "collector_number": "300",
        }
    )
    return obj


def second_wick() -> dict[str, Any]:
    """Another printing of a card the catalog already holds: same name, same
    oracle_id, a Scryfall ID the catalog has not seen."""
    obj = dict(find(load_scryfall_fixture(), WICK))
    obj.update({"id": SECOND_WICK_ID, "set": "blc", "collector_number": "300"})
    return obj


def lot(name: str, scryfall_id: str, **fields: Any) -> Lot:
    values: dict[str, Any] = {
        "name": name,
        "set_code": "fdn",
        "collector_number": "300",
        "scryfall_id": scryfall_id,
        "quantity": 1,
        "foil": "normal",
        "condition": "near_mint",
        "language": "en",
        "binder_name": BINDER,
        "binder_type": "binder",
        "added": None,
    }
    values.update(fields)
    return Lot(**values)


def write_lots(path: Path, lots: tuple[Lot, ...]) -> None:
    collection = read_collection(GOLDEN)
    write_collection(with_fields(collection, lots=lots), path)


def with_extra_lot(path: Path, extra: Lot) -> None:
    write_lots(path, (*read_collection(GOLDEN).lots, extra))


def enriched(paths: Paths, **options: Any) -> dict[str, Any]:
    """One enrich over the whole fixture: the starting point of most cases."""
    return cards.enrich(
        paths.collection,
        paths.catalog,
        paths.view,
        client=options.pop("client", fake()),
        today=options.pop("today", date(2026, 9, 14)),
        **options,
    ).to_dict()


def rows(paths: Paths) -> list[str]:
    return paths.view.read_text(encoding="utf-8").splitlines()


def row(paths: Paths, name: str) -> list[str]:
    for line in rows(paths)[3:]:
        cells = line.split("\t")
        if cells[0] == name:
            return cells
    raise AssertionError(f"no row for {name}")


class Offline(OSError):
    """What a transport raises when there is no network."""


# --- enrich -------------------------------------------------------------------


def test_enrich_builds_the_catalog_and_the_view(paths: Paths) -> None:
    client = fake()
    body = enriched(paths, client=client)
    assert body["previous_catalog"] == "none"
    assert body["catalog_written"] is True
    assert body["fetched"]["printings"] == 25
    assert body["fetched"]["tokens"] == 5
    assert body["fetched"]["requests"] >= 1
    assert body["cards"] == 23
    assert body["tokens"] == 6
    assert body["refreshed"] is None
    assert body["collection_hash"] == read_collection(GOLDEN).collection_hash
    assert body["scope"] == {"exclude_binders": []}
    assert paths.catalog.is_file() and paths.view.is_file()
    assert body["view_rows"] == len(rows(paths)) - 3
    assert client.requests == body["fetched"]["requests"]


def test_enrich_reproduces_both_goldens(paths: Paths) -> None:
    enriched(paths)
    assert paths.catalog.read_text(encoding="utf-8") == CATALOG_GOLDEN.read_text(encoding="utf-8")
    assert paths.view.read_text(encoding="utf-8") == VIEW_GOLDEN.read_text(encoding="utf-8")


def test_enrich_with_a_covering_catalog_makes_no_request(paths: Paths) -> None:
    enriched(paths)
    before = paths.catalog.read_bytes()
    view = paths.view.read_bytes()
    client = fake(fail_with=Offline("no network"))
    body = enriched(paths, client=client)
    assert body["fetched"] == {"printings": 0, "tokens": 0, "requests": 0}
    assert body["catalog_written"] is False
    assert body["previous_catalog"] == "readable"
    assert paths.catalog.read_bytes() == before
    assert paths.view.read_bytes() == view
    assert transport_of(client).calls == []


def test_enrich_offline_with_a_gap_fails_and_writes_nothing(paths: Paths) -> None:
    enriched(paths)
    before, view = paths.catalog.read_bytes(), paths.view.read_bytes()
    with_extra_lot(paths.collection, lot("Sol Ring", RING_ID))
    with pytest.raises(ToolError) as failure:
        enriched(paths, client=fake(fail_with=Offline("no network")))
    assert failure.value.error == "scryfall_unreachable"
    assert failure.value.detail["missing_printings"] == 1
    assert failure.value.detail["missing_names"] == 0
    assert failure.value.detail["message"]
    assert paths.catalog.read_bytes() == before
    assert paths.view.read_bytes() == view


def test_enrich_fetches_only_the_gap(paths: Paths) -> None:
    enriched(paths)
    before = read_catalog(paths.catalog)
    with_extra_lot(paths.collection, lot("Sol Ring", RING_ID))
    body = enriched(paths, client=fake([*load_scryfall_fixture(), sol_ring()]))
    assert body["fetched"]["printings"] == 1
    after = read_catalog(paths.catalog)
    assert after.card("Sol Ring") is not None
    assert after.cards == tuple(sorted((*before.cards, *_new(before, after)), key=lambda c: c.name))
    assert after.tokens == before.tokens


def _new(before: Catalog, after: Catalog) -> tuple[Any, ...]:
    known = {card.name for card in before.cards}
    return tuple(card for card in after.cards if card.name not in known)


def test_enrich_appends_a_printing_without_touching_the_entry(paths: Paths) -> None:
    enriched(paths)
    before = read_catalog(paths.catalog).card(WICK)
    assert before is not None
    with_extra_lot(paths.collection, lot(WICK, SECOND_WICK_ID, set_code="blc"))
    enriched(paths, client=fake([*load_scryfall_fixture(), second_wick()]))
    after = read_catalog(paths.catalog).card(WICK)
    assert after is not None
    assert len(after.printings) == len(before.printings) + 1
    assert with_fields(after, printings=before.printings) == before


def test_enrich_regenerates_an_unreadable_catalog(paths: Paths) -> None:
    paths.catalog.write_text("not json", encoding="utf-8")
    body = enriched(paths)
    assert body["previous_catalog"] == "unreadable"
    assert body["catalog_written"] is True
    assert "resolve" in body["next"]
    assert read_catalog(paths.catalog).card(WICK) is not None


def test_enrich_offline_with_an_unreadable_catalog_points_at_git(paths: Paths) -> None:
    paths.catalog.write_text("not json", encoding="utf-8")
    with pytest.raises(ToolError) as failure:
        enriched(paths, client=fake(fail_with=Offline("no network")))
    assert failure.value.error == "scryfall_unreachable"
    assert "git" in failure.value.next_step


def test_enrich_regenerates_a_foreign_schema(paths: Paths) -> None:
    paths.catalog.write_text('{"schema": 2, "cards": [], "tokens": []}', encoding="utf-8")
    assert enriched(paths)["previous_catalog"] == "unreadable"


def test_enrich_names_the_lots_of_a_printing_scryfall_does_not_know(paths: Paths) -> None:
    with_extra_lot(paths.collection, lot("Ghost Card", UNKNOWN_ID))
    with pytest.raises(ToolError) as failure:
        enriched(paths)
    assert failure.value.error == "printing_not_found"
    assert failure.value.detail["lots"] == [
        {
            "name": "Ghost Card",
            "set_code": "fdn",
            "collector_number": "300",
            "scryfall_id": UNKNOWN_ID,
        }
    ]
    assert not paths.catalog.exists() and not paths.view.exists()


def test_enrich_fails_on_a_name_the_catalog_disagrees_with(paths: Paths) -> None:
    lots = tuple(
        with_fields(entry, name="Wick, The Whorled Mind") if entry.name == WICK else entry
        for entry in read_collection(GOLDEN).lots
    )
    write_lots(paths.collection, lots)
    with pytest.raises(ToolError) as failure:
        enriched(paths)
    assert failure.value.error == "name_mismatch"
    assert failure.value.detail["catalog_written"] is False
    assert failure.value.detail["lots"] == [
        {
            "name": "Wick, The Whorled Mind",
            "set_code": "blb",
            "collector_number": "120",
            "scryfall_id": "29089810-d7fb-4abe-b729-bfabed6aed2b",
            "catalog_name": WICK,
        }
    ]
    assert not paths.catalog.exists() and not paths.view.exists()


def test_enrich_fails_when_two_oracle_ids_carry_one_name(paths: Paths) -> None:
    objects = changed("Early Winter", name="Forest")
    with pytest.raises(ToolError) as failure:
        enriched(paths, client=fake(objects))
    assert failure.value.error == "name_collision"
    assert failure.value.detail["name"] == "Forest"
    assert len(failure.value.detail["oracle_ids"]) == 2
    assert failure.value.detail["oracle_ids"][0] != failure.value.detail["oracle_ids"][1]
    assert not paths.catalog.exists()


def test_enrich_under_a_scope_that_excludes_everything(paths: Paths) -> None:
    body = enriched(paths, exclude_binders=(BINDER,))
    assert body["view_rows"] == 0
    assert body["scope"] == {"exclude_binders": [BINDER]}
    assert len(rows(paths)) == 3
    assert f'exclude-binder "{BINDER}"' in rows(paths)[0]
    assert "excluded every lot" in body["next"]


def test_enrich_fails_on_an_unknown_binder_before_any_fetch(paths: Paths) -> None:
    client = fake()
    with pytest.raises(ToolError) as failure:
        enriched(paths, client=client, exclude_binders=("Nope",))
    assert failure.value.error == "binder_unknown"
    assert failure.value.detail["unknown"] == ["Nope"]
    assert failure.value.detail["binders"] == [{"name": BINDER, "type": "binder"}]
    assert transport_of(client).calls == []


def test_enrich_scope_sums_only_the_remaining_lots(paths: Paths) -> None:
    lots = tuple(
        with_fields(entry, binder_name="A", quantity=2)
        if entry.scryfall_id == FOREST_PRINTING
        else entry
        for entry in read_collection(GOLDEN).lots
    )
    deck = lot("Forest", FOREST_PRINTING, binder_name="B", binder_type="deck", set_code="fdn")
    write_lots(paths.collection, (*lots, deck))
    enriched(paths, exclude_binders=("B",))
    assert row(paths, "Forest")[1] == "2"
    assert 'exclude-binder "B"' in rows(paths)[0]


@pytest.mark.parametrize(
    ("age", "advised"),
    [(None, True), (10, False), (30, False), (45, True)],
)
def test_enrich_advises_a_refresh_by_age(paths: Paths, age: int | None, advised: bool) -> None:
    today = date(2026, 9, 14)
    enriched(paths, today=today)
    if age is not None:
        known = read_catalog(paths.catalog)
        write_catalog(
            with_fields(known, refreshed=(today - timedelta(days=age)).isoformat()), paths.catalog
        )
    body = enriched(paths, today=today)
    assert ("cards refresh" in body["next"]) is advised


def test_enrich_next_names_the_files(paths: Paths) -> None:
    written = enriched(paths, catalog_display="data/catalog.json", view_display="data/view.tsv")
    assert "data/catalog.json" in written["next"]
    assert "data/view.tsv" in written["next"]
    unchanged = enriched(paths, catalog_display="data/catalog.json", view_display="data/view.tsv")
    assert unchanged["catalog_written"] is False
    assert "data/view.tsv" in unchanged["next"]


def test_enrich_links_a_related_token_the_catalog_already_holds(paths: Paths) -> None:
    """A card fetched after its token is already catalogued still lists it."""
    objects = load_scryfall_fixture()
    write_lots(paths.collection, tuple(entry for entry in read_collection(GOLDEN).lots))
    enriched(paths, client=fake(objects))
    known = read_catalog(paths.catalog)
    wick = known.card(WICK)
    assert wick is not None and wick.tokens == (SNAIL_ORACLE,)

    # Re-fetch Wick alone against a catalog that already owns the Snail printing.
    merged = cards.enrich(
        paths.collection,
        paths.catalog,
        paths.view,
        client=fake(objects),
        today=date(2026, 9, 14),
    )
    again = merged.catalog.card(WICK)
    assert again is not None and again.tokens == (SNAIL_ORACLE,)


def test_enrich_never_echoes_a_price(paths: Paths) -> None:
    objects = changed(WICK, prices={"usd": "13.37"}, purchase_uris={"tcgplayer": "http://x"})
    find(objects, "Early Winter").update({"layout": "frobnicate"})
    with pytest.raises(ToolError) as failure:
        enriched(paths, client=fake(objects))
    rendered = json.dumps(failure.value.to_dict(), ensure_ascii=False)
    assert failure.value.error == "layout_unknown"
    assert "13.37" not in rendered
    assert "tcgplayer" not in rendered


# --- refresh ------------------------------------------------------------------


def test_refresh_moves_only_the_date_when_nothing_changed(paths: Paths) -> None:
    enriched(paths)
    before = read_catalog(paths.catalog)
    body = cards.refresh(
        paths.collection, paths.catalog, paths.view, client=fake(), today=date(2026, 9, 14)
    ).to_dict()
    assert body["refreshed"] == "2026-09-14"
    assert body["catalog_written"] is True
    assert all(not body["changes"][key] for key in body["changes"])
    assert read_catalog(paths.catalog) == with_fields(before, refreshed="2026-09-14")


def test_refresh_dates_with_the_utc_day(paths: Paths) -> None:
    enriched(paths)
    body = cards.refresh(paths.collection, paths.catalog, paths.view, client=fake()).to_dict()
    assert body["refreshed"] == datetime.now(UTC).date().isoformat()


def test_refresh_reports_legality_and_game_changer(paths: Paths) -> None:
    enriched(paths)
    objects = changed(COLOSSUS, legalities={"commander": "banned"})
    find(objects, WICK).update({"game_changer": True})
    body = cards.refresh(
        paths.collection, paths.catalog, paths.view, client=fake(objects), today=date(2026, 9, 14)
    ).to_dict()
    assert body["changes"]["legality"] == [{"name": COLOSSUS, "from": "legal", "to": "banned"}]
    assert body["changes"]["game_changer"] == [{"name": WICK, "from": False, "to": True}]
    known = read_catalog(paths.catalog)
    colossus, wick = known.card(COLOSSUS), known.card(WICK)
    assert colossus is not None and colossus.legality == "banned"
    assert wick is not None and wick.game_changer is True


def test_refresh_reports_a_changed_face_text(paths: Paths) -> None:
    enriched(paths)
    objects = load_scryfall_fixture()
    faces = [dict(face) for face in find(objects, FARMER)["card_faces"]]
    faces[1]["oracle_text"] = "Something else entirely."
    find(objects, FARMER)["card_faces"] = faces
    body = cards.refresh(
        paths.collection, paths.catalog, paths.view, client=fake(objects), today=date(2026, 9, 14)
    ).to_dict()
    assert body["changes"]["text"] == [FARMER]


def test_refresh_writes_the_catalog_before_the_name_check(paths: Paths) -> None:
    enriched(paths)
    view = paths.view.read_bytes()
    objects = changed(COLOSSUS, name="Arbor Colossus, Reborn")
    with pytest.raises(ToolError) as failure:
        cards.refresh(
            paths.collection,
            paths.catalog,
            paths.view,
            client=fake(objects),
            today=date(2026, 9, 14),
        )
    assert failure.value.error == "name_mismatch"
    assert failure.value.detail["catalog_written"] is True
    assert failure.value.detail["changes"]["renamed"] == [
        {"from": COLOSSUS, "to": "Arbor Colossus, Reborn"}
    ]
    assert read_catalog(paths.catalog).card("Arbor Colossus, Reborn") is not None
    assert paths.view.read_bytes() == view


def test_refresh_keeps_an_entry_scryfall_no_longer_returns(paths: Paths) -> None:
    enriched(paths)
    before = read_catalog(paths.catalog).card(COLOSSUS)
    body = cards.refresh(
        paths.collection,
        paths.catalog,
        paths.view,
        client=fake(without(load_scryfall_fixture(), COLOSSUS)),
        today=date(2026, 9, 14),
    ).to_dict()
    assert body["changes"]["unresolved"] == [COLOSSUS]
    assert read_catalog(paths.catalog).card(COLOSSUS) == before


def test_refresh_without_a_catalog(paths: Paths) -> None:
    with pytest.raises(ToolError) as failure:
        cards.refresh(paths.collection, paths.catalog, paths.view, client=fake())
    assert failure.value.error == "catalog_not_found"
    assert "enrich" in failure.value.next_step


def test_refresh_requests_every_entry_in_batches(paths: Paths) -> None:
    enriched(paths)
    known = read_catalog(paths.catalog)
    client = fake()
    cards.refresh(
        paths.collection, paths.catalog, paths.view, client=client, today=date(2026, 9, 14)
    )
    asked: list[dict[str, str]] = []
    for method, url, _, body in transport_of(client).calls:
        assert method == "POST" and url.endswith("/cards/collection")
        identifiers = json.loads(body.decode("utf-8"))["identifiers"]
        assert len(identifiers) <= 75
        asked.extend(identifiers)
    assert {entry["id"] for entry in asked} == {
        entry.printings[0].scryfall_id for entry in (*known.cards, *known.tokens)
    }


# --- resolve ------------------------------------------------------------------


def resolved(paths: Paths, *names: str, client: Client | None = None) -> dict[str, Any]:
    return cards.resolve(
        list(names),
        paths.collection,
        paths.catalog,
        paths.view,
        client=client if client is not None else fake(),
    ).to_dict()


def test_resolve_from_the_catalog_makes_no_request(paths: Paths) -> None:
    enriched(paths)
    client = fake(fail_with=Offline("no network"))
    body = resolved(paths, "wick, the whorled mind", client=client)
    assert body["results"] == [
        {
            "input": "wick, the whorled mind",
            "name": WICK,
            "status": "resolved",
            "source": "catalog",
            "suggestion": None,
        }
    ]
    assert body["resolved"] == 1 and body["unresolved"] == 0
    assert transport_of(client).calls == []


def test_resolve_matches_a_face_name(paths: Paths) -> None:
    enriched(paths)
    body = resolved(paths, "Depraved Harvester", client=fake(fail_with=Offline("no network")))
    assert body["results"][0]["name"] == FARMER
    assert body["results"][0]["source"] == "catalog"


def test_resolve_fetches_an_unknown_name(paths: Paths) -> None:
    enriched(paths)
    client = fake([*load_scryfall_fixture(), sol_ring()])
    body = resolved(paths, "Sol Ring", client=client)
    assert body["results"][0] == {
        "input": "Sol Ring",
        "name": "Sol Ring",
        "status": "resolved",
        "source": "scryfall",
        "suggestion": None,
    }
    assert body["catalog_written"] is True
    assert body["fetched"]["requests"] == 1
    assert body["fetched"]["cards"] == 1
    assert read_catalog(paths.catalog).card("Sol Ring") is not None


def test_resolve_reports_a_miss_with_one_suggestion(paths: Paths) -> None:
    enriched(paths)
    before = paths.catalog.read_bytes()
    client = fake(fuzzy={"Sol Rng": sol_ring()})
    body = resolved(paths, "Sol Rng", client=client)
    assert body["results"][0] == {
        "input": "Sol Rng",
        "name": None,
        "status": "not_found",
        "source": None,
        "suggestion": "Sol Ring",
    }
    assert body["fetched"]["suggestions"] == 1
    assert body["catalog_written"] is False
    assert paths.catalog.read_bytes() == before
    assert "Sol Ring" not in paths.catalog.read_text(encoding="utf-8")


def test_resolve_survives_a_fuzzy_miss(paths: Paths) -> None:
    enriched(paths)
    body = resolved(paths, "Zzzzz Nonsense")
    assert body["results"][0]["suggestion"] is None
    assert body["unresolved"] == 1
    assert "confirming" in body["next"]


def test_resolve_keeps_input_order_and_batches_the_unknown(paths: Paths) -> None:
    enriched(paths)
    client = fake([*load_scryfall_fixture(), sol_ring()], fuzzy={})
    body = resolved(paths, WICK, "Sol Ring", "Zzzzz Nonsense", client=client)
    assert [result["input"] for result in body["results"]] == [WICK, "Sol Ring", "Zzzzz Nonsense"]
    assert body["resolved"] == 2 and body["unresolved"] == 1
    posts = [call for call in transport_of(client).calls if call[0] == "POST"]
    assert len(posts) == 1
    assert json.loads(posts[0][3].decode("utf-8"))["identifiers"] == [
        {"name": "Sol Ring"},
        {"name": "Zzzzz Nonsense"},
    ]


def test_resolve_brings_the_related_tokens_in(paths: Paths) -> None:
    body = resolved(paths, WICK)
    assert body["results"][0]["source"] == "scryfall"
    assert body["fetched"]["tokens"] == 1
    known = read_catalog(paths.catalog)
    assert known.token(SNAIL_ORACLE) is not None
    wick = known.card(WICK)
    assert wick is not None and wick.tokens == (SNAIL_ORACLE,)


def test_resolve_rebuilds_the_view_unchanged(paths: Paths) -> None:
    enriched(paths)
    before = paths.view.read_bytes()
    body = resolved(paths, "Sol Ring", client=fake([*load_scryfall_fixture(), sol_ring()]))
    assert body["catalog_written"] is True
    assert paths.view.read_bytes() == before


def test_resolve_strips_and_reports_an_empty_name(paths: Paths) -> None:
    enriched(paths)
    client = fake(fail_with=Offline("no network"))
    body = resolved(paths, "   ", client=client)
    assert body["results"][0] == {
        "input": "",
        "name": None,
        "status": "not_found",
        "source": None,
        "suggestion": None,
    }
    assert transport_of(client).calls == []


def test_resolve_with_no_catalog_starts_from_empty(paths: Paths) -> None:
    body = resolved(paths, WICK)
    assert body["catalog_written"] is True
    assert paths.catalog.is_file()


def test_resolve_fails_on_an_unreadable_catalog(paths: Paths) -> None:
    paths.catalog.write_text("not json", encoding="utf-8")
    with pytest.raises(ToolError) as failure:
        resolved(paths, WICK)
    assert failure.value.error == "catalog_unreadable"


# --- the names file -----------------------------------------------------------


def test_names_from_file_ignores_blank_and_comment_lines(tmp_path: Path) -> None:
    path = tmp_path / "names.txt"
    path.write_text(f"# a list\n{WICK}\n\n  Forest  \n# done\nSol Ring\n", encoding="utf-8")
    assert cards.names_from_file(path) == (WICK, "Forest", "Sol Ring")


def test_names_from_file_without_a_file(tmp_path: Path) -> None:
    with pytest.raises(ToolError) as failure:
        cards.names_from_file(tmp_path / "missing.txt")
    assert failure.value.error == "names_file_unreadable"
    assert failure.value.detail["path"].endswith("missing.txt")


def test_names_from_file_that_is_not_utf8(tmp_path: Path) -> None:
    path = tmp_path / "names.txt"
    path.write_bytes(b"\xff\xfe\x00Forest")
    with pytest.raises(ToolError) as failure:
        cards.names_from_file(path)
    assert failure.value.error == "names_file_unreadable"


# --- what every result promises -----------------------------------------------


def test_every_result_carries_a_next_sentence(paths: Paths) -> None:
    first = enriched(paths)
    second = cards.refresh(
        paths.collection, paths.catalog, paths.view, client=fake(), today=date(2026, 9, 14)
    ).to_dict()
    third = resolved(paths, WICK)
    for body in (first, second, third):
        assert isinstance(body["next"], str) and body["next"]
        assert json.loads(json.dumps(body)) == body


def test_no_output_carries_a_price(paths: Paths) -> None:
    objects = changed(WICK, prices={"usd": "13.37"}, purchase_uris={"tcgplayer": "http://x"})
    body = enriched(paths, client=fake(objects))
    rendered = json.dumps(body, ensure_ascii=False)
    assert "13.37" not in rendered and "purchase" not in rendered
    for text in (paths.catalog, paths.view):
        content = text.read_text(encoding="utf-8")
        assert "13.37" not in content and "purchase" not in content


def test_collection_failures_pass_through(tmp_path: Path) -> None:
    missing = Paths(tmp_path / "no.json", tmp_path / "catalog.json", tmp_path / "view.tsv")
    with pytest.raises(ToolError) as failure:
        enriched(missing)
    assert failure.value.error == "collection_not_found"


def test_view_rows_counts_owned_cards(paths: Paths) -> None:
    body = enriched(paths)
    collection: Collection = read_collection(GOLDEN)
    owned = {lot.scryfall_id for lot in collection.lots}
    known = read_catalog(paths.catalog)
    names = {
        owner.name
        for owner in (known.owner_of(scryfall_id) for scryfall_id in owned)
        if owner is not None and known.card(owner.name) is owner
    }
    assert body["view_rows"] == len(names)
