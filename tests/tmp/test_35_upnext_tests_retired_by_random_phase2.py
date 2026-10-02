"""Checkpoint for plan 20-35 phase 2: the up-next dislike tests are restored, un-skipped, in tests/active, and the behaviour they guard holds on the session Engine and through the Client.

- Each test first requires its restored counterpart in tests/active (test_dislike_profile.py's two centroid tests over cooking and linux with DRAW_SEED 7, test_dislikes.py's two up-next tests over linux and football x both routes) to exist, carry no skip, skipif or xfail mark, take the planned fixtures and be parametrised over exactly those values.
- It then runs that restored test with its own case's values: it passes on the session Engine and a Client of its own, and fails with an AssertionError under each mutant of what it guards. For test_dislike_profile's two tests the mutant is an Engine blind to `dislike_centroids` that answers a repeated request with the same page. The absent/present test has three mutants: a Client that keeps disliked rows, one that serves the first disliking profile's up-next page to keyless requests, and one that serves it to other profiles. The lean-away test's mutant is a Client that sends no centroids. A skip or xfail raised inside its body fails the checkpoint.
- For cooking and linux on the Engine, the seed=7 16-row up-next page repeats, and the same seeded request carrying the centroid of either of its least similar pair (cosine < 0.7) has leading 8 other rows less close to that video than the plain page, with the margin closeness(d1) - closeness(d2) lower on the d1 page than on the d2 page.
- For the same seeds, on 5 plain home pages liked from the seed, a pair from the seeded up-next page (cosine < 0.7) has a clearly similar row on every plain page; on 5 home pages carrying either one's centroid those rows sit lower on average than on the plain pages, and the d1-minus-d2 position lean is higher on average on the d1 pages than on the d2 pages.
- For linux and football on POST /recommendations and /videos/similar through the Client, pinned with conftest's `pin_upnext`: the keyless 16-row pin serves exactly the pool's first 16; a profile disliking its 9th row is served the pool's first 17 without it (16 rows) under the 17-row pin, and the first 16 without it (15 rows) under the 16-row pin; the keyless page still holds all 16, and a bystander disliking the first row holds all but that one.
- Under the 16-row pin, each of two profiles disliking one of the keyless page's least similar pair (cosine < 0.7) is served the 16 rows without its own, with leading 8 other rows less close to its disliked video than the keyless page's, and the d1 profile's margin below the d2 profile's.
"""
from __future__ import annotations

import copy
import importlib
import inspect
import json
import sys
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

import conftest  # noqa: E402
from conftest import closeness, cosine, dataset, embedding_of, engine, unpublished_client  # noqa: E402,F401

PROFILE_QUERIES = ("cooking", "linux")
DISLIKE_QUERIES = ("linux", "football")
ROUTES = ("/recommendations", "/videos/similar")
# The draw seed the plan fixes for test_dislike_profile; the values below were observed at it.
DRAW_SEED = 7
PAGE = 16
LEADING = 8
HOME_DRAWS = 5
# Above the 99th percentile of cosine between random videos in this corpus (0.59, measured).
CLEARLY_SIMILAR = 0.6
# Their own Engine rate buckets, apart from conftest's 192.0.2.150 and phase 1's .151/.152; the Client's own requests reach the Engine as 127.0.0.1.
UPNEXT_HEADERS = {"X-Client-IP": "192.0.2.154"}
HOME_HEADERS = {"X-Client-IP": "192.0.2.155"}
MUTANT_HEADERS = {"X-Client-IP": "192.0.2.156"}


def _restored(module: str, name: str, fixtures: set[str], params: dict[str, set[str]], **constants) -> Callable[..., None]:
    """The named test is in tests/active/<module>.py, not skipped, taking these fixtures, parametrised over exactly these values, beside these module constants; returns it."""
    mod = importlib.import_module(module)
    assert {k: getattr(mod, k, None) for k in constants} == constants, {k: getattr(mod, k, None) for k in constants}
    assert Path(mod.__file__).resolve().parent == ACTIVE, mod.__file__
    fn = getattr(mod, name, None)
    assert callable(fn), f"{module}.{name} is not restored in tests/active"
    module_marks = getattr(mod, "pytestmark", [])
    marks = [*(module_marks if isinstance(module_marks, list) else [module_marks]), *getattr(fn, "pytestmark", [])]
    assert not [m.name for m in marks if m.name in ("skip", "skipif", "xfail")], [m.name for m in marks]
    assert fixtures <= set(inspect.signature(fn).parameters), list(inspect.signature(fn).parameters)
    got = {m.args[0]: {*m.args[1]} for m in marks if m.name == "parametrize"}
    assert got == params, got
    return fn


def _run(restored: Callable[..., None], **args) -> AssertionError | None:
    """Run a restored test with these values: the AssertionError it raised, or None when it passed; a skip or xfail raised in its body fails the checkpoint."""
    try:
        restored(**args)
    except AssertionError as exc:
        return exc
    except (pytest.skip.Exception, pytest.xfail.Exception) as exc:
        pytest.fail(f"{restored.__name__} skips or xfails in its body: {exc!r}")
    return None


class _CentroidBlind:
    """The session Engine as one that ignores `dislike_centroids`, on its own rate bucket: a request is sent without them and its first answer is replayed for every repeat, so centroid pages are the plain page, home ones included."""

    def __init__(self, engine):
        self.engine, self.pages = engine, {}

    def request(self, method: str, path: str, headers: dict | None = None, body: dict | None = None):
        plain = None if body is None else {k: v for k, v in body.items() if k != "dislike_centroids"}
        key = (method, path, json.dumps(plain, sort_keys=True))
        if key not in self.pages:
            self.pages[key] = self.engine.request(method, path, headers={**MUTANT_HEADERS, **(headers or {})}, body=plain)
        return copy.deepcopy(self.pages[key])


class _DislikeLeak:
    """The Client as one that serves the first disliking profile's up-next page in place of keyless ones (keyless=True) or of other profiles' (keyless=False)."""

    def __init__(self, client, keyless: bool):
        self.client, self.keyless, self.first = client, keyless, None

    def request(self, method: str, path: str, headers: dict | None = None, body: dict | None = None):
        key = (headers or {}).get("X-Profile-Key")
        if path == "/api/user-action" and (body or {}).get("action") == "dislike" and self.first is None:
            self.first = key
        elif path.startswith(ROUTES) and self.first is not None and (key is None) == self.keyless and key != self.first:
            headers = {**(headers or {}), "X-Profile-Key": self.first}
        return self.client.request(method, path, headers=headers, body=body)


@contextmanager
def _own_client(tmp_path: Path, engine, monkeypatch, name: str):
    """An unpublished Client of its own on the session Engine: one server mints at most 5 profiles (PROFILE_MINT_MAX_REQUESTS), fewer than this checkpoint and each restored run take together."""
    (tmp_path / name).mkdir()
    clients = conftest._engine_client(tmp_path / name, engine, monkeypatch, "activitypub")
    try:
        yield next(clients)
    finally:
        clients.close()


def _keys(rows: list[dict]) -> list[tuple[str, str]]:
    return [(r["video_id"], r["instance_domain"]) for r in rows]


def _without(rows: list[dict], *dropped: dict) -> list[tuple[str, str]]:
    """The sorted keys of rows, less the dropped ones."""
    return sorted(set(_keys(rows)) - set(_keys(list(dropped))))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _least_pair(dataset, rows: list[dict]) -> tuple[dict, dict]:
    """The least similar pair of rows on a page, asserted under cosine 0.7."""
    vecs = [embedding_of(dataset, r["video_id"], r["instance_domain"]) for r in rows]
    i, j = min(((i, j) for i in range(len(rows)) for j in range(i + 1, len(rows))), key=lambda p: cosine(vecs[p[0]], vecs[p[1]]))
    assert cosine(vecs[i], vecs[j]) < 0.7, cosine(vecs[i], vecs[j])
    return rows[i], rows[j]


def _others(rows: list[dict], d1: dict, d2: dict) -> list[dict]:
    """The leading rows of a page other than the two disliked videos."""
    return [r for r in rows if r["video_id"] not in (d1["video_id"], d2["video_id"])][:LEADING]


def _margin(dataset, rows: list[dict], d1: dict, d2: dict) -> float:
    others = _others(rows, d1, d2)
    return closeness(dataset, others, d1) - closeness(dataset, others, d2)


# --- dislike centroids on the Engine (test_dislike_profile.py) -------------------------------


def _engine_seed(engine, query: str) -> dict:
    status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=1")
    assert status == 200 and body["rows"], body
    return body["rows"][0]


def _seeded_upnext(engine, seed: dict, headers: dict, body: dict) -> list[dict]:
    path = f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={PAGE}&seed={DRAW_SEED}"
    status, payload = engine.request("POST", path, headers=headers, body=body)
    assert status == 200 and len(payload["rows"]) == PAGE, payload
    return payload["rows"]


def _centroid_body(dataset, disliked: dict) -> dict:
    space = dataset.execute("SELECT model_name FROM video_embeddings LIMIT 1").fetchone()[0]
    return {"space": space, "vectors": [embedding_of(dataset, disliked["video_id"], disliked["instance_domain"])]}


def _similar_ids(dataset, rows: list[dict], video: dict) -> set[str]:
    """The video_ids on a page, other than the video itself, clearly similar to it."""
    target = embedding_of(dataset, video["video_id"], video["instance_domain"])
    return {r["video_id"] for r in rows if r["video_id"] != video["video_id"] and cosine(embedding_of(dataset, r["video_id"], r["instance_domain"]), target) >= CLEARLY_SIMILAR}


def _covered_pair(dataset, rows: list[dict], plain_pages: list[list[dict]]) -> tuple[dict, dict]:
    """The least similar pair on the up-next page, under cosine 0.7, each with a row other than the pair clearly similar to it on every plain home page."""
    vecs = [embedding_of(dataset, r["video_id"], r["instance_domain"]) for r in rows]
    near = [[_similar_ids(dataset, page, r) for page in plain_pages] for r in rows]
    for i, j in sorted(((i, j) for i in range(len(rows)) for j in range(i + 1, len(rows))), key=lambda p: cosine(vecs[p[0]], vecs[p[1]])):
        if cosine(vecs[i], vecs[j]) >= 0.7:
            break
        pair = {rows[i]["video_id"], rows[j]["video_id"]}
        if all(ids - pair for k in (i, j) for ids in near[k]):
            return rows[i], rows[j]
    pytest.fail("control: no pair under cosine 0.7 on the seeded up-next page has a clearly similar row on every plain home page")


def _position(dataset, rows: list[dict], d1: dict, d2: dict, own: dict) -> float:
    """Mean page position of the rows, other than the two dislikes, clearly similar to `own`; a page holding none counts as its length."""
    target = embedding_of(dataset, own["video_id"], own["instance_domain"])
    positions = [p for p, r in enumerate(rows) if r["video_id"] not in (d1["video_id"], d2["video_id"]) and cosine(embedding_of(dataset, r["video_id"], r["instance_domain"]), target) >= CLEARLY_SIMILAR]
    return sum(positions) / len(positions) if positions else float(len(rows))


@pytest.mark.parametrize("query", PROFILE_QUERIES)
def test_a_seeded_upnext_page_carrying_a_dislike_centroid_leads_with_rows_less_close_to_that_video(engine, dataset, query):
    restored = _restored("test_dislike_profile", "test_an_upnext_page_carrying_a_dislike_centroid_moves_away_from_that_disliked_video", {"engine", "dataset", "query"}, {"query": set(PROFILE_QUERIES)}, DRAW_SEED=DRAW_SEED)
    assert _run(restored, engine=engine, dataset=dataset, query=query) is None  # C1
    # A plan-shaped stand-in failed here on a tie (0.4508 = 0.4508 cooking, 0.5663 = 0.5663 linux); a body asserting nothing passes it.
    assert isinstance(_run(restored, engine=_CentroidBlind(engine), dataset=dataset, query=query), AssertionError), "the restored test passes on an Engine blind to the centroid"  # C1
    seed = _engine_seed(engine, query)
    plain = _seeded_upnext(engine, seed, UPNEXT_HEADERS, {})
    # Control: the seeded draw repeats, so a centroid page differs from the plain one only by the centroid (observed equal for both seeds).
    assert _keys(_seeded_upnext(engine, seed, UPNEXT_HEADERS, {})) == _keys(plain)
    d1, d2 = _least_pair(dataset, plain)
    pages = {}
    for own in (d1, d2):
        rows = _seeded_upnext(engine, seed, UPNEXT_HEADERS, {"dislike_centroids": _centroid_body(dataset, own)})
        pages[own["video_id"]] = rows
        # Observed 0.4256 < 0.4508 and 0.4503 < 0.4601 (cooking), 0.4654 < 0.5663 and 0.4835 < 0.6130 (linux); an ignored centroid serves the plain page again and ties.
        assert closeness(dataset, _others(rows, d1, d2), own) < closeness(dataset, _others(plain, d1, d2), own), own["video_id"]  # C1
    # Observed -0.0400 < -0.0041 (cooking), -0.0661 < 0.0233 (linux).
    assert _margin(dataset, pages[d1["video_id"]], d1, d2) < _margin(dataset, pages[d2["video_id"]], d1, d2)  # C1


@pytest.mark.parametrize("query", PROFILE_QUERIES)
def test_home_pages_carrying_a_dislike_centroid_place_rows_clearly_similar_to_it_lower_on_average(engine, dataset, query):
    restored = _restored("test_dislike_profile", "test_home_pages_carrying_a_dislike_centroid_place_videos_similar_to_it_lower", {"engine", "dataset", "query"}, {"query": set(PROFILE_QUERIES)}, DRAW_SEED=DRAW_SEED)
    assert _run(restored, engine=engine, dataset=dataset, query=query) is None  # C1
    # Replayed home pages hold the coverage control and tie: a plan-shaped stand-in failed on mean 5.0 > 5.0 (cooking) and 13.0 > 13.0 (linux).
    assert isinstance(_run(restored, engine=_CentroidBlind(engine), dataset=dataset, query=query), AssertionError), "the restored test passes on an Engine blind to the centroid"  # C1
    seed = _engine_seed(engine, query)
    upnext = _seeded_upnext(engine, seed, HOME_HEADERS, {})
    likes = [{"uuid": seed["video_uuid"], "host": seed["instance_domain"]}]

    def home(extra: dict) -> list[dict]:
        status, body = engine.request("POST", "/recommendations", headers=HOME_HEADERS, body={"likes": likes, **extra})
        assert status == 200 and body["rows"], body
        return body["rows"]

    # Home takes no draw seed and its pages differ request to request (observed), so the pair is chosen on the very plain pages compared below.
    plain = [home({}) for _ in range(HOME_DRAWS)]
    d1, d2 = _covered_pair(dataset, upnext, plain)
    before = {own["video_id"]: [_position(dataset, rows, d1, d2, own) for rows in plain] for own in (d1, d2)}
    for own in (d1, d2):
        # Control: every plain page holds a row clearly similar to it, so a shaped page has something to place lower.
        assert all(p < len(rows) for p, rows in zip(before[own["video_id"]], plain)), before[own["video_id"]]
    shaped = {own["video_id"]: [home({"dislike_centroids": _centroid_body(dataset, own)}) for _ in range(HOME_DRAWS)] for own in (d1, d2)}
    for own in (d1, d2):
        after = [_position(dataset, rows, d1, d2, own) for rows in shaped[own["video_id"]]]
        # Means, not extremes (operator's choice): single unseeded pages overlapped once (44.0 vs 43.0); observed means 46.0 vs 14.0 and 44.7 vs 27.05 (cooking), about 41 vs 11 (linux).
        assert _mean(after) > _mean(before[own["video_id"]]), (own["video_id"], after, before[own["video_id"]])  # C1
    lean_d1 = [_position(dataset, rows, d1, d2, d1) - _position(dataset, rows, d1, d2, d2) for rows in shaped[d1["video_id"]]]
    lean_d2 = [_position(dataset, rows, d1, d2, d1) - _position(dataset, rows, d1, d2, d2) for rows in shaped[d2["video_id"]]]
    # The min/max form failed on one linux run (-0.38 < 5.8); means were 17.05 vs -12.1 there and 8.8 vs -32.67 on cooking.
    assert _mean(lean_d1) > _mean(lean_d2), (lean_d1, lean_d2)  # C1


# --- a profile's dislikes through the Client (test_dislikes.py) ------------------------------


def _client_seed(client, query: str) -> dict:
    status, body = client.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=1")
    assert status == 200 and body["rows"], body
    return body["rows"][0]


def _client_upnext(client, route: str, seed: dict, headers: dict | None, body: dict) -> list[dict]:
    status, payload = client.request("POST", f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={PAGE}", headers=headers, body=body)
    assert status == 200, payload
    return payload["rows"]


def _profile_disliking(client, video: dict) -> dict[str, str]:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    key = {"X-Profile-Key": body["key"]}
    status, body = client.request("POST", "/api/user-action", headers=key, body={"action": "dislike", "uuid": video["video_uuid"], "host": video["instance_domain"]})
    assert status == 200, body
    return key


def _pins(engine, route: str, seed: dict) -> tuple[list[dict], dict, dict]:
    """The pool's first 17 rows, and the bodies pinning an up-next page to its first 16 and to all 17."""
    pool = conftest.upnext_pool(engine, route, seed)
    # Observed 318 (linux) and 311 (football) rows on both routes.
    assert len(pool) > PAGE + 1, len(pool)
    head = pool[:PAGE + 1]
    return head, {"exclude": conftest.pin_upnext(engine, route, seed, head[:PAGE])}, {"exclude": conftest.pin_upnext(engine, route, seed, head)}


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("query", DISLIKE_QUERIES)
def test_a_profile_s_pinned_client_upnext_page_leaves_out_its_disliked_video_which_keyless_and_bystander_pages_hold(unpublished_client, engine, tmp_path, monkeypatch, route, query):
    restored = _restored("test_dislikes", "test_a_disliked_video_is_absent_from_the_profile_s_full_upnext_page_and_present_for_others", {"unpublished_client", "engine", "route", "query"}, {"route": set(ROUTES), "query": set(DISLIKE_QUERIES)})
    with _own_client(tmp_path, engine, monkeypatch, "restored") as own:
        assert _run(restored, unpublished_client=own, engine=engine, route=route, query=query) is None  # C2
    # A Client that keeps disliked rows still leaves the row off the 17-pin page (its centroid ranks it 17th and the cut drops it), so only the keyed 16-pin page shows the filter; a plan-shaped stand-in failed there.
    with _own_client(tmp_path, engine, monkeypatch, "unfiltered") as own, monkeypatch.context() as patch:
        patch.setattr(conftest.client_server, "filter_disliked", lambda rows, dropped: rows)
        assert isinstance(_run(restored, unpublished_client=own, engine=engine, route=route, query=query), AssertionError), "the restored test passes on a Client that keeps disliked rows"  # C2
    # The stand-in failed on its keyless assertion under the keyless leak, and on its bystander assertion under the bystander leak.
    for keyless in (True, False):
        with _own_client(tmp_path, engine, monkeypatch, f"leak-{keyless}") as own:
            assert isinstance(_run(restored, unpublished_client=_DislikeLeak(own, keyless), engine=engine, route=route, query=query), AssertionError), f"the restored test passes when the dislike leaks to {'keyless' if keyless else 'bystander'} pages"  # C2
    client = unpublished_client
    seed = _client_seed(client, query)
    head, pin16, pin17 = _pins(engine, route, seed)
    keyless = _client_upnext(client, route, seed, None, pin16)
    # Control: the pinned keyless page is exactly the pool's first 16 (an unpinned one shared 1-4 of them, observed), so the disliked row would otherwise be served.
    assert sorted(_keys(keyless)) == sorted(_keys(head[:PAGE])), _keys(keyless)
    disliked = keyless[PAGE // 2]
    key = _profile_disliking(client, disliked)
    bystander = _profile_disliking(client, keyless[0])

    # The Client over-fetches 32, the Engine serves the 17 pinned rows whole, and the Client drops the disliked one: a full page without it.
    assert sorted(_keys(_client_upnext(client, route, seed, key, pin17))) == _without(head, disliked)  # C2
    # Under the 16-row pin no row is cut, so the disliked row's absence is the Client's filter, not the centroid ranking it past the page (observed 15 rows).
    assert sorted(_keys(_client_upnext(client, route, seed, key, pin16))) == _without(head[:PAGE], disliked)  # C2
    assert sorted(_keys(_client_upnext(client, route, seed, None, pin16))) == sorted(_keys(head[:PAGE]))  # C2
    # The bystander's own dislike is honoured (its first row goes), and the other profile's disliked row stays.
    assert sorted(_keys(_client_upnext(client, route, seed, bystander, pin16))) == _without(head[:PAGE], keyless[0])  # C2


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("query", DISLIKE_QUERIES)
def test_a_profile_s_pinned_client_upnext_page_leads_with_rows_less_close_to_its_disliked_video(unpublished_client, engine, dataset, tmp_path, monkeypatch, route, query):
    restored = _restored("test_dislikes", "test_a_profile_s_upnext_page_leans_away_from_its_disliked_video", {"unpublished_client", "engine", "dataset", "route", "query"}, {"route": set(ROUTES), "query": set(DISLIKE_QUERIES)})
    with _own_client(tmp_path, engine, monkeypatch, "restored") as own:
        assert _run(restored, unpublished_client=own, engine=engine, dataset=dataset, route=route, query=query) is None  # C2
    # Without centroids the keyed pages keep the keyless order: a plan-shaped stand-in failed on a tie (0.6969 = 0.6969 linux, 0.5232 = 0.5232 football).
    with _own_client(tmp_path, engine, monkeypatch, "blind") as own, monkeypatch.context() as patch:
        patch.setattr(conftest.client_server, "load_centroids", lambda *args: None)
        assert isinstance(_run(restored, unpublished_client=own, engine=engine, dataset=dataset, route=route, query=query), AssertionError), "the restored test passes on a Client that sends no centroids"  # C2
    client = unpublished_client
    seed = _client_seed(client, query)
    head, pin16, _ = _pins(engine, route, seed)
    keyless = _client_upnext(client, route, seed, None, pin16)
    assert sorted(_keys(keyless)) == sorted(_keys(head[:PAGE])), _keys(keyless)
    # Observed cosine 0.552 (linux) and 0.410 (football).
    d1, d2 = _least_pair(dataset, keyless)
    page_d1 = _client_upnext(client, route, seed, _profile_disliking(client, d1), pin16)
    page_d2 = _client_upnext(client, route, seed, _profile_disliking(client, d2), pin16)
    # Control: each page is the same pinned set less its own disliked row, so what follows measures order alone.
    assert sorted(_keys(page_d1)) == _without(head[:PAGE], d1) and sorted(_keys(page_d2)) == _without(head[:PAGE], d2)
    # Observed 0.6570 < 0.6969 and 0.6095 < 0.6346 (linux), 0.4748 < 0.5232 and 0.4938 < 0.5321 (football); without the centroid the leading others keep the keyless order and tie.
    assert closeness(dataset, _others(page_d1, d1, d2), d1) < closeness(dataset, _others(keyless, d1, d2), d1)  # C2
    assert closeness(dataset, _others(page_d2, d1, d2), d2) < closeness(dataset, _others(keyless, d1, d2), d2)  # C2
    # Observed -0.0090 < 0.0730 (linux), -0.0280 < 0.0102 (football).
    assert _margin(dataset, page_d1, d1, d2) < _margin(dataset, page_d2, d1, d2)  # C2
