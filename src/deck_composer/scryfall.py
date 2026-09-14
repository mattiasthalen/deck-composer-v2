"""Scryfall: the requests this project makes and the payload it accepts.

Owns the API surface (ADR-0004) and nothing else: the endpoints, the batch
size, the spacing between requests, the identifying headers, the closed layout
and legality vocabularies (R1), and the projection of a Scryfall object into
the catalog's `Card` and `Token` records (R6, R7). Nothing else parses a
Scryfall payload; nothing here reads or writes a file, and no field outside R6
is ever carried out of this module.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from deck_composer.catalog import Card, Face, Printing, Token
from deck_composer.errors import ToolError

# A transport takes a method, a URL, the headers and the body, and answers with
# a status and the raw body. Injected so tests never reach the network.
Transport = Callable[[str, str, dict[str, str], bytes], tuple[int, bytes]]

API = "https://api.scryfall.com"
COLLECTION_URL = f"{API}/cards/collection"
NAMED_URL = f"{API}/cards/named"
REPOSITORY = "https://github.com/mattiasthalen/deck-composer-v2"
# R5: at most 75 identifiers per request, requests at least 100 ms apart.
BATCH = 75
SPACING = 0.1
TIMEOUT = 30.0
# Deliberately small (Brief 1 non-goals): one extra attempt on the statuses
# that mean "ask again", nothing on a transport failure, so an offline run
# fails at once. Every attempt counts towards `Client.requests`.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
ATTEMPTS = 2

# R1. A layout in neither set fails with `layout_unknown`; growing either one
# is a code change.
CARD_LAYOUTS = frozenset(
    {
        "normal",
        "split",
        "flip",
        "transform",
        "modal_dfc",
        "meld",
        "leveler",
        "class",
        "case",
        "saga",
        "adventure",
        "mutate",
        "prototype",
        "battle",
        "prepare",
        "reversible_card",
        "augment",
        "host",
    }
)
TOKEN_LAYOUTS = frozenset(
    {
        "token",
        "double_faced_token",
        "emblem",
        "art_series",
        "planar",
        "scheme",
        "vanguard",
    }
)
LEGALITIES = frozenset({"legal", "not_legal", "banned", "restricted"})
COLORS = frozenset({"W", "U", "B", "R", "G"})

_UPDATE_CLIENT = (
    "Scryfall's payload no longer matches what the catalog reads; update the projection in "
    "src/deck_composer/scryfall.py, then run the operation again."
)


def urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes
) -> tuple[int, bytes]:
    """The default transport: one request over HTTPS, no session, no state. An
    HTTP error status is an answer, not an exception; everything else raises."""
    request = urllib.request.Request(url, data=body or None, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as answer:
        return answer.code, answer.read()


class Client:
    """One caller's conversation with Scryfall: sequential, spaced, identified.

    `requests` counts every request made over the client's lifetime, retries
    included, so a caller can report what a run cost.
    """

    def __init__(
        self,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        version: str = "unknown",
    ) -> None:
        self._transport: Transport = transport if transport is not None else urllib_transport
        self._sleep = sleep
        self._headers = {
            "Accept": "application/json",
            "User-Agent": f"deck-composer/{version} (+{REPOSITORY})",
        }
        self.requests = 0

    def collection(
        self, identifiers: Sequence[Mapping[str, str]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Fetch every identifier through `POST /cards/collection`, in batches of
        at most 75 (R5). Answers the objects found and the identifiers Scryfall
        did not know, both in request order."""
        data: list[dict[str, Any]] = []
        not_found: list[dict[str, Any]] = []
        wanted = list(identifiers)
        for start in range(0, len(wanted), BATCH):
            body = json.dumps({"identifiers": wanted[start : start + BATCH]}).encode("utf-8")
            status, payload = self._payload("POST", COLLECTION_URL, body)
            data.extend(_objects(payload, "data", status))
            not_found.extend(_objects(payload, "not_found", status))
        return data, not_found

    def fuzzy(self, name: str) -> str | None:
        """One suggestion for a name that did not resolve (R14), or None when
        Scryfall answers 404. The answer is a name, never stored."""
        url = f"{NAMED_URL}?{urllib.parse.urlencode({'fuzzy': name})}"
        status, body = self._send("GET", url, b"", allow_404=True)
        if status == 404:
            return None
        payload = _decode(body, status, "GET", url)
        suggestion = payload.get("name")
        if not isinstance(suggestion, str) or not suggestion:
            raise ToolError(
                "payload_invalid",
                {"name": name, "field": "name", "message": "a non-empty string is required"},
                _UPDATE_CLIENT,
            )
        return suggestion

    def _payload(self, method: str, url: str, body: bytes) -> tuple[int, dict[str, Any]]:
        status, answer = self._send(method, url, body)
        return status, _decode(answer, status, method, url)

    def _send(
        self, method: str, url: str, body: bytes, *, allow_404: bool = False
    ) -> tuple[int, bytes]:
        status = 0
        answer = b""
        for attempt in range(ATTEMPTS):
            status, answer = self._attempt(method, url, body)
            if 200 <= status < 300 or (allow_404 and status == 404):
                return status, answer
            if status not in RETRY_STATUSES or attempt + 1 == ATTEMPTS:
                break
        raise ToolError(
            "scryfall_error",
            {
                "status": status,
                "message": f"Scryfall answered HTTP {status} for {method} {_path(url)}.",
            },
            "Wait for Scryfall to recover, then run the operation again.",
        )

    def _attempt(self, method: str, url: str, body: bytes) -> tuple[int, bytes]:
        if self.requests:
            self._sleep(SPACING)
        self.requests += 1
        headers = dict(self._headers)
        if body:
            headers["Content-Type"] = "application/json"
        try:
            return self._transport(method, url, headers, body)
        except Exception as failure:
            raise ToolError(
                "scryfall_unreachable",
                {"message": f"{type(failure).__name__}: {failure}"},
                "Connect to the network, then run the operation again.",
            ) from failure


def project(obj: Mapping[str, Any]) -> Card | Token:
    """One Scryfall object in, one catalog record out (R6). Classification is by
    `layout` alone (R1); every required field is checked and every field outside
    R6 is dropped (R7). `Card.tokens` is left empty here and filled by
    `project_all`, which sees the token objects fetched alongside."""
    identity = _identity(obj)
    layout = _text(obj, "layout", identity)
    if layout in TOKEN_LAYOUTS:
        return _token(obj, identity, layout)
    if layout in CARD_LAYOUTS:
        return _card(obj, identity, layout)
    raise ToolError(
        "layout_unknown",
        {
            "layout": layout,
            "name": obj.get("name") if isinstance(obj.get("name"), str) else None,
            "scryfall_id": identity.get("scryfall_id"),
            "constant": "CARD_LAYOUTS or TOKEN_LAYOUTS",
        },
        f"Scryfall uses the layout {layout!r}; add it to CARD_LAYOUTS or TOKEN_LAYOUTS in "
        "src/deck_composer/scryfall.py, then run the operation again.",
    )


def project_all(objects: Sequence[Mapping[str, Any]]) -> list[Card | Token]:
    """Project every object, then link each card to the tokens fetched with it:
    `Card.tokens` holds the `oracle_id` of every token object in this list whose
    Scryfall ID the card relates to (R5, R6), sorted. A related id absent from
    the list is not linked; the caller fetches related tokens in the same run."""
    records = [project(obj) for obj in objects]
    oracle_ids = {
        str(obj["id"]): record.oracle_id
        for obj, record in zip(objects, records, strict=True)
        if isinstance(record, Token)
    }
    linked: list[Card | Token] = []
    for obj, record in zip(objects, records, strict=True):
        if isinstance(record, Card):
            related = {
                oracle_ids[scryfall_id]
                for scryfall_id in related_token_ids(obj)
                if scryfall_id in oracle_ids
            }
            record = replace(record, tokens=tuple(sorted(related)))
        linked.append(record)
    return linked


def related_token_ids(obj: Mapping[str, Any]) -> tuple[str, ...]:
    """The Scryfall IDs of the object's related tokens: the `all_parts` entries
    with component `token`, in order, without repeats. Other components
    (`meld_part`, `meld_result`, `combo_piece`) are never followed (R5)."""
    found: list[str] = []
    parts = obj.get("all_parts")
    if not isinstance(parts, list):
        return ()
    for part in parts:
        if not isinstance(part, Mapping) or part.get("component") != "token":
            continue
        scryfall_id = part.get("id")
        if isinstance(scryfall_id, str) and scryfall_id and scryfall_id not in found:
            found.append(scryfall_id)
    return tuple(found)


def _card(obj: Mapping[str, Any], identity: dict[str, Any], layout: str) -> Card:
    legalities = obj.get("legalities")
    if not isinstance(legalities, Mapping):
        raise _payload_invalid(identity, "legalities", "an object is required")
    legality = legalities.get("commander")
    if legality not in LEGALITIES:
        raise _payload_invalid(
            identity, "legalities.commander", "one of legal, not_legal, banned, restricted"
        )
    game_changer = obj.get("game_changer")
    if not isinstance(game_changer, bool):
        raise _payload_invalid(identity, "game_changer", "a boolean is required")
    return Card(
        name=_text(obj, "name", identity),
        oracle_id=_oracle_id(obj, identity),
        layout=layout,
        type_line=_text(obj, "type_line", identity),
        mana_cost=_optional_text(obj, "mana_cost", identity),
        cmc=_cmc(obj, identity),
        colors=_colors(obj, "colors", identity),
        color_identity=_required_colors(obj, "color_identity", identity),
        produced_mana=_optional_strings(obj, "produced_mana", identity),
        oracle_text=_optional_text(obj, "oracle_text", identity),
        keywords=_required_strings(obj, "keywords", identity),
        legality=str(legality),
        game_changer=game_changer,
        edhrec_rank=_rank(obj, identity),
        faces=_faces(obj, identity),
        tokens=(),
        printings=(_printing(obj, identity),),
    )


def _token(obj: Mapping[str, Any], identity: dict[str, Any], layout: str) -> Token:
    """A token record carries no legality, colours or rank: no consumer reads
    them, and a token is never a deck candidate (lexicon)."""
    return Token(
        oracle_id=_oracle_id(obj, identity),
        name=_text(obj, "name", identity),
        layout=layout,
        type_line=_text(obj, "type_line", identity),
        oracle_text=_optional_text(obj, "oracle_text", identity),
        printings=(_printing(obj, identity),),
    )


def _printing(obj: Mapping[str, Any], identity: dict[str, Any]) -> Printing:
    return Printing(
        scryfall_id=_text(obj, "id", identity),
        set=_text(obj, "set", identity),
        set_type=_text(obj, "set_type", identity),
        collector_number=_text(obj, "collector_number", identity),
        rarity=_text(obj, "rarity", identity),
        released_at=_text(obj, "released_at", identity),
    )


def _faces(obj: Mapping[str, Any], identity: dict[str, Any]) -> tuple[Face, ...] | None:
    """The faces of a multi-faced card, or None. A card with a single face is
    the card itself, so `faces` is never a one-element tuple (Brief 4)."""
    raw = obj.get("card_faces")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise _payload_invalid(identity, "card_faces", "an array is required")
    if len(raw) < 2:
        return None
    faces: list[Face] = []
    for face in raw:
        if not isinstance(face, Mapping):
            raise _payload_invalid(identity, "card_faces", "every face must be an object")
        faces.append(
            Face(
                name=_text(face, "name", identity),
                mana_cost=_optional_text(face, "mana_cost", identity),
                type_line=_optional_text(face, "type_line", identity),
                colors=_colors(face, "colors", identity),
                oracle_text=_optional_text(face, "oracle_text", identity),
            )
        )
    return tuple(faces)


def _oracle_id(obj: Mapping[str, Any], identity: dict[str, Any]) -> str:
    """R6: the object's `oracle_id`, or the faces' when the object has none, as
    on a `reversible_card`."""
    value = obj.get("oracle_id")
    if isinstance(value, str) and value:
        return value
    for face in obj.get("card_faces") or []:
        if isinstance(face, Mapping):
            from_face = face.get("oracle_id")
            if isinstance(from_face, str) and from_face:
                return from_face
    raise _payload_invalid(identity, "oracle_id", "required on the object or on a face")


def _rank(obj: Mapping[str, Any], identity: dict[str, Any]) -> int | None:
    value = obj.get("edhrec_rank")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise _payload_invalid(identity, "edhrec_rank", "an integer is required")
    return _two_significant_figures(value)


def _two_significant_figures(rank: int) -> int:
    """R6, ADR-0006: rounded half up, so 9518 is 9500, 22870 is 23000, 9950 is
    10000 and 120 stays 120. A rank is a rough position, not a measurement."""
    digits = len(str(rank))
    if digits <= 2:
        return rank
    step = 10 ** (digits - 2)
    return (rank + step // 2) // step * step


def _cmc(obj: Mapping[str, Any], identity: dict[str, Any]) -> float:
    value = obj.get("cmc")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _payload_invalid(identity, "cmc", "a number is required")
    return int(value) if float(value).is_integer() else float(value)


def _text(obj: Mapping[str, Any], field: str, identity: dict[str, Any]) -> str:
    value = obj.get(field)
    if not isinstance(value, str) or not value:
        raise _payload_invalid(identity, field, "a non-empty string is required")
    return value


def _optional_text(obj: Mapping[str, Any], field: str, identity: dict[str, Any]) -> str | None:
    value = obj.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _payload_invalid(identity, field, "a string is required")
    return value


def _colors(obj: Mapping[str, Any], field: str, identity: dict[str, Any]) -> tuple[str, ...] | None:
    value = obj.get(field)
    if value is None:
        return None
    return _letters(value, field, identity)


def _required_colors(
    obj: Mapping[str, Any], field: str, identity: dict[str, Any]
) -> tuple[str, ...]:
    value = obj.get(field)
    if value is None:
        raise _payload_invalid(identity, field, "an array of the letters W, U, B, R, G is required")
    return _letters(value, field, identity)


def _letters(value: Any, field: str, identity: dict[str, Any]) -> tuple[str, ...]:
    if not isinstance(value, list) or any(letter not in COLORS for letter in value):
        raise _payload_invalid(identity, field, "an array of the letters W, U, B, R, G is required")
    return tuple(str(letter) for letter in value)


def _required_strings(
    obj: Mapping[str, Any], field: str, identity: dict[str, Any]
) -> tuple[str, ...]:
    value = obj.get(field)
    if value is None:
        raise _payload_invalid(identity, field, "an array of strings is required")
    return _strings(value, field, identity)


def _optional_strings(
    obj: Mapping[str, Any], field: str, identity: dict[str, Any]
) -> tuple[str, ...] | None:
    value = obj.get(field)
    if value is None:
        return None
    return _strings(value, field, identity)


def _strings(value: Any, field: str, identity: dict[str, Any]) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _payload_invalid(identity, field, "an array of strings is required")
    return tuple(str(item) for item in value)


def _identity(obj: Mapping[str, Any]) -> dict[str, Any]:
    """What a failure names the object by: its Scryfall ID, or its name when the
    object has no id. The payload itself is never echoed (R18)."""
    scryfall_id = obj.get("id")
    if isinstance(scryfall_id, str) and scryfall_id:
        return {"scryfall_id": scryfall_id}
    name = obj.get("name")
    return {"name": name if isinstance(name, str) else None}


def _payload_invalid(identity: dict[str, Any], field: str, message: str) -> ToolError:
    return ToolError(
        "payload_invalid", {**identity, "field": field, "message": message}, _UPDATE_CLIENT
    )


def _objects(payload: Mapping[str, Any], key: str, status: int) -> list[dict[str, Any]]:
    value = payload.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ToolError(
            "scryfall_error",
            {
                "status": status,
                "message": f"Scryfall's answer has no list of objects under {key!r}.",
            },
            "Wait for Scryfall to recover, then run the operation again.",
        )
    return list(value)


def _decode(body: bytes, status: int, method: str, url: str) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as failure:
        raise ToolError(
            "scryfall_error",
            {
                "status": status,
                "message": f"Scryfall's answer to {method} {_path(url)} is not JSON.",
            },
            "Wait for Scryfall to recover, then run the operation again.",
        ) from failure
    if not isinstance(payload, dict):
        raise ToolError(
            "scryfall_error",
            {
                "status": status,
                "message": f"Scryfall's answer to {method} {_path(url)} is not an object.",
            },
            "Wait for Scryfall to recover, then run the operation again.",
        )
    return payload


def _path(url: str) -> str:
    """The path of a URL, without the query: a caller's name is data, never part
    of a failure message beyond the field that named it (Brief 4)."""
    return urllib.parse.urlsplit(url).path or url
