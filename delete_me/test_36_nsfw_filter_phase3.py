"""A listing request is served no row whitelist.db flags nsfw = 1 unless it carries exactly nsfw=1, and the gateway forwards that opt-in, against the session Engine on the repo's dataset.

- The set of keys whitelist.db flags nsfw = 1, read through the read-only `dataset` connection, is non-empty.
- Ten listing paths are each sent with nsfw missing, empty, "0", "true" and " 1": POST /recommendations with mode recommendations (carrying five flagged likes), hot, recent and random; up-next for one flagged seed on POST /recommendations, POST /videos/similar and GET /videos/{id}/similar; POST /recommendations?random=1; the raw-vector POST /recommendations for that seed's embedding; and GET /api/v1/search/videos?q=hentai. Every response is 200, holds rows, and holds no flagged key. The random feeds are drawn 12 times per value and the mixed feed 3 times.
- Before each of those requests, the same path with nsfw=1 returns at least one flagged key on the same Engine (within 12 draws for the random feeds, 3 for the mixed feed). For mode=recommendations this means the mixer honours the opt-in and then filters the next request, so its flag is read per request, not frozen at build time.
- POST /recommendations with mode popular is sent with the same five values, and every response is 200, holds rows, and holds no flagged key. It has no nsfw=1 control: its first flagged row sits at position 2650 of its order, past the 96 rows after at most 500 excluded that the feed can reach, so on this dataset its filtered and opted-in pages are alike and its check passes whatever the filter does.
- Through the Client backend in front of the session Engine, mode=recent on POST /recommendations and POST /videos/similar, and q=hentai on GET /api/v1/search/videos, each with nsfw=1, answer 200 with at least one flagged key. The same requests without nsfw answer 200 with rows and no flagged key.
- Those three gateway requests are each sent with nsfw missing, empty, "0", "true" and " 1", each after the same route with nsfw=1 returns at least one flagged key, and every response is 200, holds rows, and holds no flagged key.
- Through a Client backend in front of a closed Engine port, GET /api/video without nsfw passes the allowlist and fails upstream (502), and with nsfw=1 is refused 400 {"error": "Unknown query parameter: nsfw"}.

Every Engine request carries its own X-Client-IP, and every gateway request its own X-Forwarded-For. That the gateway sends the Engine the resolved address as X-Client-IP, keeping gateway requests out of one shared bucket, is not asserted here; tests/active/test_server.py::test_engine_receives_the_resolved_address_as_x_client_ip asserts it.
"""
from __future__ import annotations

import importlib.util
import itertools
import json
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

# pytest loads tests/active/conftest.py only for tests under it, so the live fixtures are imported here to register them.
from conftest import client_backend, dataset, embedding_of, engine, engine_client  # noqa: E402,F401

# One fresh address per request from the benchmark range, clear of the 192.0.2.x buckets tests/active uses.
CLIENT_IPS = (f"198.18.{n // 250}.{n % 250 + 1}" for n in itertools.count())
# Up-next caps a page at one row per channel; this flagged seed's neighbourhood spans ten flagged channels, so its seed=11 page at limit 96 carries 10 flagged rows, and its raw-vector page 37 of 96 (observed).
SEED_ID, SEED_HOST = "59b6239b-15c6-4bc4-b5e6-6ebac4ea9751", "810video.com"
DRAW_SEED = 11
# 84 of the top 100 matches are flagged (observed), and 244 match in all.
SEARCH_QUERY = "hentai"
SEARCH_LIMIT = 100
# Flagged videos from the SEARCH_QUERY results: liked, they pull the like layer into a flagged neighbourhood, and a mixed page carried 4 or 5 flagged rows in each of 6 draws (observed).
LIKES = [{"uuid": uuid, "host": "video02.videohost.top"} for uuid in ("f4e114a2-e70e-4a3c-af92-3efe3071abbc", "0e9ab678-8f3c-4305-97c9-ba9586536999", "4577ad2f-8462-4c78-8212-c4470a4f6db5", "0b385f12-aaeb-435b-9282-7e466cbaf282", "b9ff92e2-6b40-4396-9ed9-1c7f30031dcb")]
LISTINGS = ["mode=recommendations", "mode=hot", "mode=recent", "mode=random", "upnext POST /recommendations", "upnext POST /videos/similar", "upnext GET /videos/{id}/similar", "random=1", "vector", "search"]
# The random cache is 0.6% flagged, so a 96-row draw held 0 to 2 flagged rows (observed): 12 draws hold none about once in a thousand runs.
DRAWS = {"mode=random": 12, "random=1": 12, "mode=recommendations": 3}
# Every value but exactly "1"; parse_qs drops the empty one, so it arrives as missing.
NSFW_VALUES = {"missing": "", "empty": "&nsfw=", "0": "&nsfw=0", "true": "&nsfw=true", "space-1": f"&nsfw={quote(' 1')}"}
# Recent's sixth row is flagged (observed), inside the gateway's 48-row feed page.
GATEWAY_LISTINGS = {
    "/recommendations": ("POST", "/recommendations?mode=recent", {}),
    "/videos/similar": ("POST", "/videos/similar?mode=recent", {}),
    "/api/v1/search/videos": ("GET", f"/api/v1/search/videos?q={SEARCH_QUERY}&limit={SEARCH_LIMIT}", None),
}


def _default_limit() -> int:
    spec = importlib.util.spec_from_file_location("engine_server_config", ROOT / "engine" / "server" / "api" / "server_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return int(module.BATCH_SIZE)


# The largest page the Engine serves: twice its default.
LIMIT = 2 * _default_limit()


@pytest.fixture(scope="module")
def flagged(dataset) -> set[tuple[str, str]]:
    keys = {(r["video_id"], r["instance_domain"]) for r in dataset.execute("SELECT video_id, instance_domain FROM videos WHERE nsfw = 1")}
    assert keys, "control: whitelist.db flags no video nsfw = 1"
    return keys


def _listing(dataset, listing: str) -> tuple[str, str, dict | None]:
    """The method, path and body of one listing request, without nsfw."""
    upnext = f"id={SEED_ID}&host={SEED_HOST}&limit={LIMIT}&seed={DRAW_SEED}"
    if listing == "mode=recommendations":
        return "POST", f"/recommendations?mode=recommendations&limit={LIMIT}", {"likes": LIKES}
    if listing.startswith("mode="):
        return "POST", f"/recommendations?{listing}&limit={LIMIT}", {}
    if listing == "upnext POST /recommendations":
        return "POST", f"/recommendations?{upnext}", {}
    if listing == "upnext POST /videos/similar":
        return "POST", f"/videos/similar?{upnext}", {}
    if listing == "upnext GET /videos/{id}/similar":
        return "GET", f"/videos/{SEED_ID}/similar?host={SEED_HOST}&limit={LIMIT}&seed={DRAW_SEED}", None
    if listing == "random=1":
        return "POST", f"/recommendations?random=1&limit={LIMIT}", {}
    if listing == "vector":
        return "POST", f"/recommendations?vector={quote(json.dumps(embedding_of(dataset, SEED_ID, SEED_HOST)))}&limit={LIMIT}", {}
    return "GET", f"/api/v1/search/videos?q={SEARCH_QUERY}&limit={SEARCH_LIMIT}", None


def _keys(http, method: str, path: str, body: dict | None, header: str) -> list[tuple[str, str]]:
    status, payload = http.request(method, path, headers={header: next(CLIENT_IPS)}, body=body)
    assert status == 200 and isinstance(payload, dict) and "rows" in payload, (path[:160], status, payload)
    return [(r["video_id"], r["instance_domain"]) for r in payload["rows"]]


@pytest.mark.parametrize("nsfw", NSFW_VALUES)
@pytest.mark.parametrize("listing", LISTINGS)
def test_a_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some(engine, dataset, flagged, listing, nsfw):
    method, path, body = _listing(dataset, listing)
    draws = DRAWS.get(listing, 1)
    # Sent first on the same Engine: a mixer whose flag froze at build time serves no flagged row here.
    shown: set[tuple[str, str]] = set()
    for _ in range(draws):
        shown = set(_keys(engine, method, f"{path}&nsfw=1", body, "X-Client-IP")) & flagged
        if shown:
            break
    assert shown, f"control: {listing} with nsfw=1 served no flagged row in {draws} draws"
    for _ in range(draws):
        keys = _keys(engine, method, f"{path}{NSFW_VALUES[nsfw]}", body, "X-Client-IP")
        assert keys, f"{listing} served an empty page"  # a handler answering every filtered request with no rows is no filter
        assert not set(keys) & flagged, sorted(set(keys) & flagged)[:5]  # C1


@pytest.mark.parametrize("nsfw", NSFW_VALUES)
def test_a_popular_request_without_exactly_nsfw_1_gets_rows_and_no_flagged_row(engine, dataset, flagged, nsfw):
    # A smoke check the operator exempted: Popular's first flagged row is at position 2650 of its order (observed), and the feed reaches no further than 96 rows past 500 excluded, so no nsfw=1 control can be armed and this passes whatever the filter does.
    method, path, body = _listing(dataset, "mode=popular")
    keys = _keys(engine, method, f"{path}{NSFW_VALUES[nsfw]}", body, "X-Client-IP")
    assert keys, "mode=popular served an empty page"
    assert not set(keys) & flagged, sorted(set(keys) & flagged)[:5]  # C1


@pytest.mark.parametrize("nsfw", NSFW_VALUES)
@pytest.mark.parametrize("route", GATEWAY_LISTINGS)
def test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some(engine_client, flagged, route, nsfw):
    method, path, body = GATEWAY_LISTINGS[route]
    assert set(_keys(engine_client, method, f"{path}&nsfw=1", body, "X-Forwarded-For")) & flagged, f"control: {route} with nsfw=1 served no flagged row"
    keys = _keys(engine_client, method, f"{path}{NSFW_VALUES[nsfw]}", body, "X-Forwarded-For")
    assert keys, f"{route} served an empty page"
    # The gateway strips the values it forwards, so one forwarding nsfw that way turns " 1" into the opt-in; "true" and "0" catch one that normalises or opts in on the key alone.
    assert not set(keys) & flagged, sorted(set(keys) & flagged)[:5]  # C1


@pytest.mark.parametrize("route", GATEWAY_LISTINGS)
def test_the_gateway_forwards_nsfw_1_to_the_engine_on_the_three_listing_routes(engine_client, flagged, route):
    method, path, body = GATEWAY_LISTINGS[route]
    status, payload = engine_client.request(method, f"{path}&nsfw=1", headers={"X-Forwarded-For": next(CLIENT_IPS)}, body=body)
    # A gateway refusing nsfw answers 400 here; one dropping or rewriting it gets the Engine's filtered page.
    assert status == 200 and isinstance(payload, dict) and "rows" in payload, (route, status, payload)  # C2
    assert {(r["video_id"], r["instance_domain"]) for r in payload["rows"]} & flagged, f"{route} with nsfw=1 served no flagged row"  # C2
    plain = _keys(engine_client, method, path, body, "X-Forwarded-For")
    # The same request without the opt-in is filtered, so the flagged rows above are the forwarded nsfw=1's doing.
    assert plain and not set(plain) & flagged, sorted(set(plain) & flagged)[:5]  # C2


def test_the_gateway_still_refuses_nsfw_on_api_video(client_backend):
    status, body = client_backend.request("GET", "/api/video?id=x&host=y")
    assert status == 502, (status, body)  # control: without nsfw the request passes the allowlist and is proxied to the closed Engine port
    status, body = client_backend.request("GET", "/api/video?id=x&host=y&nsfw=1")
    assert (status, body) == (400, {"error": "Unknown query parameter: nsfw"})  # scope guard: the opt-in is allowlisted on the three listing routes only
