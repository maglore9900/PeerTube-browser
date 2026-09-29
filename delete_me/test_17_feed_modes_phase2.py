"""The Engine refuses an unknown feed `mode` on unseeded requests only, and the gateway passes that refusal through.

Against the session `engine` fixture (the real Engine on the repo's dataset):

- An unseeded POST /recommendations whose `mode` is `bogus`, `HOT` or `home` (none of them in `FEED_MODES`) is answered 400
  with exactly `{"error": "Unknown mode", "allowed": list(FEED_MODES)}`, `FEED_MODES` read from `handlers.similar` under the
  Engine interpreter. `FEED_MODES` exists with no value repeated, and each of the five modes the requirements name, each value
  in `FEED_MODES`, an empty `mode` and no `mode` are answered 200.
- A seeded POST /recommendations (a real video's `id` and `host`, `seed=11`) with each of the five modes, `mode=bogus`,
  `mode=HOT` or an empty `mode` is answered 200 with the same `seed` payload (`mode` "upnext") and the same ordered rows as that request without `mode`.

Against `engine_client` (a real Client backend in front of that same Engine):

- `?mode=bogus` reaches the caller as the Engine's own 400 `Unknown mode` body, the answer the Engine gives it directly.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.parse import quote

import pytest

# tests/tmp has no conftest of its own, so the active suite's fixtures and helpers are imported from it; fixtures imported here are registered as this module's.
ACTIVE_DIR = Path(__file__).resolve().parents[1] / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))
from conftest import ENGINE_PY, ROOT, engine, engine_client  # noqa: E402,F401

SERVER_DIR = ROOT / "engine" / "server"
# The values the requirements name for `mode`, sent as inputs so a tuple that dropped one is refused on the wire, not compared against a copy of the spec.
REQUIRED_MODES = ["recommendations", "hot", "recent", "random", "popular"]
# Near misses: an unknown word, a known mode in the wrong case, and the Engine's internal profile name.
UNKNOWN_MODES = ["bogus", "HOT", "home"]
SEEDED_MODES = [*REQUIRED_MODES, "bogus", "HOT", ""]
UPNEXT_PAGE = 8
# Its own rate-limit bucket: the session Engine allows 60 requests a minute per client IP and path, and other tests share 127.0.0.1's.
HEADERS = {"X-Client-IP": "192.0.2.172"}
# The gateway trusts its loopback peer, so this is the address it resolves and sends the Engine as X-Client-IP.
GATEWAY_HEADERS = {"X-Forwarded-For": "192.0.2.172"}

# Runs under the Engine interpreter: importing handlers.similar needs numpy and faiss, which only its pixi env carries.
# A missing FEED_MODES prints null rather than failing the import, so the import stays a control and the constant's absence reaches the claim.
_FEED_MODES_CHILD = textwrap.dedent(
    """
    import json, sys
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    import handlers.similar as similar
    print(json.dumps(list(similar.FEED_MODES) if hasattr(similar, "FEED_MODES") else None))
    """
)


def _feed_modes() -> list[str] | None:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", _FEED_MODES_CHILD, str(SERVER_DIR), str(SERVER_DIR / "api")], cwd=SERVER_DIR / "api", capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter imported handlers.similar
    return json.loads(run.stdout.strip().splitlines()[-1])


def _keys(rows: list[dict]) -> list[tuple[str, str]]:
    return [(r["video_id"], r["instance_domain"]) for r in rows]


@pytest.mark.parametrize("mode", UNKNOWN_MODES)
def test_an_unseeded_request_with_a_mode_outside_feed_modes_is_answered_400_naming_them(engine, mode):
    status, body = engine.request("POST", f"/recommendations?mode={mode}&limit={UPNEXT_PAGE}", headers=HEADERS, body={})
    # Before this phase the mode was ignored: 200 with a home page (observed for all three).
    assert (status, body.get("error")) == (400, "Unknown mode"), (status, body.get("seed"))  # C1
    modes = _feed_modes()
    assert modes is not None and mode not in modes, modes  # control: FEED_MODES exists and the value sent is outside it
    assert body == {"error": "Unknown mode", "allowed": list(modes)}  # C1


def test_every_feed_mode_and_a_missing_or_empty_mode_is_served_not_refused(engine):
    modes = _feed_modes()
    assert modes is not None and len(modes) == len(set(modes)), modes  # C1: FEED_MODES exists with no value repeated
    # A validator refusing every mode passes the 400 test, and a tuple missing a required mode refuses it; both fail here.
    for suffix in [f"&mode={mode}" for mode in dict.fromkeys([*REQUIRED_MODES, *modes])] + ["", "&mode="]:
        status, body = engine.request("POST", f"/recommendations?limit={UPNEXT_PAGE}{suffix}", headers=HEADERS, body={})
        assert status == 200 and "error" not in body and "rows" in body, (suffix, status, body.get("error"))  # C1


def test_a_seeded_request_is_served_the_same_upnext_whatever_its_mode(engine):
    status, found = engine.request("GET", "/api/v1/search/videos?q=linux&limit=1", headers=HEADERS)
    assert status == 200 and found["rows"], found
    seed = found["rows"][0]
    # seed=11 fixes the up-next draw, so a page is a function of the request and pages can be compared row for row.
    path = f"/recommendations?id={quote(seed['video_uuid'])}&host={quote(seed['instance_domain'])}&limit={UPNEXT_PAGE}&seed=11"
    status, plain = engine.request("POST", path, headers=HEADERS, body={})
    assert status == 200 and plain["seed"].get("mode") == "upnext" and len(plain["rows"]) == UPNEXT_PAGE, (status, plain.get("seed"))
    status, again = engine.request("POST", path, headers=HEADERS, body={})
    assert status == 200 and _keys(again["rows"]) == _keys(plain["rows"]), "control: the seeded draw repeats without mode"

    for mode in SEEDED_MODES:
        status, body = engine.request("POST", f"{path}&mode={mode}", headers=HEADERS, body={})
        # Validating seeded requests answers bogus 400; dispatching on mode serves another feed, whose seed is not this video's.
        assert status == 200, (mode, status, body)  # C2
        assert body["seed"] == plain["seed"], (mode, body["seed"])  # C2
        assert _keys(body["rows"]) == _keys(plain["rows"]), mode  # C2


def test_the_gateway_passes_the_engines_unknown_mode_400_through(engine, engine_client):
    path = f"/recommendations?mode=bogus&limit={UPNEXT_PAGE}"
    status, body = engine_client.request("POST", path, headers=GATEWAY_HEADERS, body={})
    # Before this phase the gateway forwarded mode and the Engine ignored it: 200 with a home page (observed).
    assert (status, body.get("error")) == (400, "Unknown mode"), (status, body.get("seed"))  # C1
    # The Engine's own answer to the same request: a gateway that dropped mode, refused it itself or wrapped the 400 differs from it.
    assert (status, body) == engine.request("POST", path, headers=HEADERS, body={})  # C1
    modes = _feed_modes()
    assert body == {"error": "Unknown mode", "allowed": modes}  # C1
