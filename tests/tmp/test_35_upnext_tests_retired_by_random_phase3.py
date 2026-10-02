"""Checkpoint for plan 20-35 phase 3: the up-next block tests are restored, un-skipped, in tests/active, and the behaviour they guard holds on pinned up-next pages through the Client and through the frontend modules.

- Each test first requires its restored counterparts in tests/active (test_blocks.py's surfaces test over /recommendations, /videos/similar and search, and its stays-full test over both routes; test_frontend_blocks.py's module-block test and its refused-key test) to exist, carry no skip, skipif or xfail mark, and take the planned fixtures and parameters.
- It then runs each restored test on a Client of its own (the surfaces test at the up-next route of its own case only; its `search` case is run by the suite as part of test_blocks.py): it passes, and it fails with an AssertionError under each mutant of what it guards. Both test_blocks.py tests have the mutant of a Client that drops `exclude` from up-next requests, so their pages are not pinned. The surfaces test's others are a Client that does not filter up-next pages, one that serves the first blocking profile's up-next page to keyless requests, and one that serves it to other profiles. The stays-full test's are a Client that keeps blocked rows and one that cuts the over-fetched page to one page before filtering it. The module-block test's are a Client that does not filter up-next pages and one that does not filter search, and every keyed up-next request its passing run sends through the Client carries exactly the `/recommendations` pin of the music seed's pool's first 8. The refused-key test only has to pass. A skip or xfail raised inside a body fails the checkpoint.
- On POST /recommendations and /videos/similar through the Client, pinned with conftest's `pin_upnext` to the pool's first 8 rows: the keyless page is exactly those 8; a profile blocking its first row's channel and another row's account is served those 8 less every row on that channel or account; the keyless page is still all 8, and a bystander blocking a third row's channel is served all 8 less that one.
- Pinned to the pool's first 11 rows, the keyless limit-11 page is exactly those 11, and a profile blocking the channels of its first 3 is served a full 8-row page that is exactly the other 8, with none of the 3 channels on it.
- The node runner's up-next fetch, given the `/recommendations` pin of the pool's first 8 through `_run`'s exclude, returns exactly those 8 rows' channels for a fresh profile; after `blockVideoSource` for the first row's channel and for a search row's channel, it returns the other 7, and the search fetch, which held the search row's channel before, still returns rows but not that channel.
"""
from __future__ import annotations

import importlib
import inspect
import json
import sys
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

import conftest  # noqa: E402
from conftest import engine, engine_client  # noqa: E402,F401

ROUTES = ("/recommendations", "/videos/similar")
SURFACES = (*ROUTES, "search")
SEARCH_PATH = "/api/v1/search/videos"
# test_blocks.py's search, whose first row seeds its up-next pages.
SEARCH = f"{SEARCH_PATH}?q=music&limit=20"
# test_frontend_blocks.py's search (QUERY = "music"), whose first row seeds the runner's up-next fetch.
FRONTEND_SEARCH = f"{SEARCH_PATH}?q=music"
PAGE = 8
# The stays-full pin: a page plus the three rows the blocks remove.
STAYS_FULL = PAGE + 3


def _restored(module: str, name: str, fixtures: set[str], params: dict[str, set[str]]) -> Callable[..., None]:
    """The named test is in tests/active/<module>.py, not skipped, taking these fixtures, parametrised over at least these values; returns it."""
    mod = importlib.import_module(module)
    assert Path(mod.__file__).resolve().parent == ACTIVE, mod.__file__
    fn = getattr(mod, name, None)
    assert callable(fn), f"{module}.{name} is not restored in tests/active"
    module_marks = getattr(mod, "pytestmark", [])
    marks = [*(module_marks if isinstance(module_marks, list) else [module_marks]), *getattr(fn, "pytestmark", [])]
    assert not [m.name for m in marks if m.name in ("skip", "skipif", "xfail")], [m.name for m in marks]
    assert fixtures <= set(inspect.signature(fn).parameters), list(inspect.signature(fn).parameters)
    got = {m.args[0]: {*m.args[1]} for m in marks if m.name == "parametrize"}
    assert all(values <= got.get(arg, set()) for arg, values in params.items()), got
    return fn


def _outcome(restored: Callable[..., None], **available) -> AssertionError | None:
    """Run a restored test with those of these values its signature takes: the AssertionError it raised, or None when it passed; a skip or xfail raised in its body fails the checkpoint."""
    taken = inspect.signature(restored).parameters
    try:
        restored(**{k: v for k, v in available.items() if k in taken})
    except AssertionError as exc:
        return exc
    except (pytest.skip.Exception, pytest.xfail.Exception) as exc:
        pytest.fail(f"{restored.__name__} skips or xfails in its body: {exc!r}")
    return None


@contextmanager
def _own_client(tmp_path: Path, engine, monkeypatch, name: str):
    """A Client of its own on the session Engine: one server mints at most 5 profiles (PROFILE_MINT_MAX_REQUESTS), fewer than this checkpoint and each restored run take together."""
    (tmp_path / name).mkdir()
    clients = conftest._engine_client(tmp_path / name, engine, monkeypatch, "bridge")
    try:
        yield next(clients)
    finally:
        clients.close()


def _workdir(tmp_path: Path, name: str) -> Path:
    (tmp_path / name).mkdir()
    return tmp_path / name


class _BlockLeak:
    """The Client as one that serves the first blocking profile's up-next page in place of keyless ones (keyless=True) or of other profiles' (keyless=False)."""

    def __init__(self, client, keyless: bool):
        self.client, self.keyless, self.first = client, keyless, None
        self.base = client.base

    def request(self, method: str, path: str, headers: dict | None = None, body: dict | None = None):
        key = (headers or {}).get("X-Profile-Key")
        if method == "POST" and path == "/api/profile/blocks" and self.first is None:
            self.first = key
        elif path.startswith(ROUTES) and self.first is not None and (key is None) == self.keyless and key != self.first:
            headers = {**(headers or {}), "X-Profile-Key": self.first}
        return self.client.request(method, path, headers=headers, body=body)


class _PinDropped:
    """The Client as one that drops `exclude` from up-next requests, so a pinned page is a fresh draw from the whole pool."""

    def __init__(self, client):
        self.client, self.base = client, client.base

    def request(self, method: str, path: str, headers: dict | None = None, body: dict | None = None):
        if path.startswith(ROUTES) and body:
            body = {k: v for k, v in body.items() if k != "exclude"}
        return self.client.request(method, path, headers=headers, body=body)


def _cut_before_filter(original: Callable[..., bytes | None]) -> Callable[..., bytes | None]:
    """`_filter_payload` that cuts the Engine's page to one page before filtering it, so rows a block removes are not refilled from the over-fetch."""
    def cut(payload: bytes, row_filter, page_size: int | None) -> bytes | None:
        page = json.loads(payload)
        if page_size is not None:
            page["rows"] = page["rows"][:page_size]
        return original(json.dumps(page).encode("utf-8"), row_filter, page_size)
    return cut


def _recording_upnext(original: Callable[..., None], pins: list[frozenset[tuple[str, str]] | None]) -> Callable[..., None]:
    """`_proxy_engine_request` that records the `exclude` keys of each keyed up-next request it forwards (None when it carries none), then forwards it unchanged."""
    def proxy(self, method: str, path: str, *args, **kwargs) -> None:
        if path in ROUTES and self.headers.get("X-Profile-Key") is not None:
            exclude = (kwargs.get("body") or {}).get("exclude")
            pins.append(None if exclude is None else _pin_keys(exclude))
        return original(self, method, path, *args, **kwargs)
    return proxy


def _pin_keys(exclude: list[dict[str, str]]) -> frozenset[tuple[str, str]]:
    return frozenset((e["id"], e["host"]) for e in exclude)


def _keys(rows: list[dict]) -> list[tuple[str, str]]:
    return sorted((r["video_id"], r["instance_domain"]) for r in rows)


def _channel(row: dict) -> tuple[str, str]:
    return (row["instance_domain"], row["channel_id"])


def _search_rows(client, path: str) -> list[dict]:
    status, body = client.request("GET", path)
    assert status == 200 and body["rows"], body
    return body["rows"]


def _pinned(engine, route: str, seed: dict, size: int) -> tuple[list[dict], dict]:
    """The pool's first `size` rows, and the body pinning an up-next page to them."""
    pool = conftest.upnext_pool(engine, route, seed)
    assert len(pool) > STAYS_FULL, len(pool)
    chosen = pool[:size]
    return chosen, {"exclude": conftest.pin_upnext(engine, route, seed, chosen)}


def _upnext(client, route: str, seed: dict, limit: int, key: str | None, pin: dict) -> list[dict]:
    headers = {"X-Profile-Key": key} if key else {}
    status, body = client.request("POST", f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={limit}", headers=headers, body=pin)
    assert status == 200, body
    return body["rows"]


def _mint(client) -> str:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return body["key"]


def _block(client, key: str, kind: str, row: dict) -> None:
    status, body = client.request("POST", "/api/profile/blocks", headers={"X-Profile-Key": key}, body={"kind": kind, "uuid": row["video_uuid"], "host": row["instance_domain"]})
    assert status == 201, body


def _distinct(rows: list[dict], *taken: dict) -> dict:
    """A row sharing neither a channel nor an account with any row in `taken`."""
    return next(r for r in rows if _channel(r) not in {_channel(t) for t in taken} and r["account_url"] not in {t["account_url"] for t in taken})


# --- test_blocks.py: a profile's blocks on pinned up-next pages through the gateway ---------


@pytest.mark.parametrize("route", ROUTES)
def test_a_pinned_upnext_page_leaves_out_the_blocker_s_channel_and_account_which_keyless_and_bystander_pages_keep(engine_client, engine, tmp_path, monkeypatch, route):
    restored = _restored("test_blocks", "test_blocked_channel_and_account_leave_only_the_blocking_profile_s_page", {"engine_client", "engine", "surface"}, {"surface": set(SURFACES)})
    with _own_client(tmp_path, engine, monkeypatch, "restored") as own:
        assert _outcome(restored, engine_client=own, engine=engine, surface=route) is None  # C1
    # Without the pin the keyless page is a draw of 8 from a 32-row window (it shared 1-3 rows with the pool's first 8, observed), so only a restored test pinned and controlled against those 8 fails here.
    with _own_client(tmp_path, engine, monkeypatch, "unpinned") as own:
        assert isinstance(_outcome(restored, engine_client=_PinDropped(own), engine=engine, surface=route), AssertionError), "the restored test passes when its up-next pages are not pinned"  # C1
    # Unfiltered, the blocker's limit-8 request is served the 8 pinned rows whole, blocked ones included.
    with _own_client(tmp_path, engine, monkeypatch, "unfiltered") as own, monkeypatch.context() as patch:
        patch.setattr(conftest.client_server, "FILTERED_ROUTES", frozenset({SEARCH_PATH}))
        assert isinstance(_outcome(restored, engine_client=own, engine=engine, surface=route), AssertionError), "the restored test passes on a Client that does not filter up-next pages"  # C1
    for keyless in (True, False):
        with _own_client(tmp_path, engine, monkeypatch, f"leak-{keyless}") as own:
            assert isinstance(_outcome(restored, engine_client=_BlockLeak(own, keyless), engine=engine, surface=route), AssertionError), f"the restored test passes when the blocks leak to {'keyless' if keyless else 'bystander'} pages"  # C1

    client = engine_client
    seed = _search_rows(client, SEARCH)[0]
    chosen, pin = _pinned(engine, route, seed, PAGE)
    keyless = _upnext(client, route, seed, PAGE, None, pin)
    # Control: the pinned keyless page is exactly the pool's first 8, so the targets taken from it would otherwise be served.
    assert _keys(keyless) == _keys(chosen), _keys(keyless)
    blocked_channel = keyless[0]
    blocked_account = _distinct(keyless, blocked_channel)
    unrelated = _distinct(list(reversed(keyless)), blocked_channel, blocked_account)
    blocker = _mint(client)
    _block(client, blocker, "channel", blocked_channel)
    _block(client, blocker, "account", blocked_account)
    bystander = _mint(client)
    _block(client, bystander, "channel", unrelated)

    left = [r for r in chosen if _channel(r) != _channel(blocked_channel) and r["account_url"] != blocked_account["account_url"]]
    assert _keys(_upnext(client, route, seed, PAGE, blocker, pin)) == _keys(left)  # C1
    assert _keys(_upnext(client, route, seed, PAGE, None, pin)) == _keys(chosen)  # C1
    assert _keys(_upnext(client, route, seed, PAGE, bystander, pin)) == _keys([r for r in chosen if _channel(r) != _channel(unrelated)])  # C1


@pytest.mark.parametrize("route", ROUTES)
def test_a_pinned_upnext_page_losing_three_rows_to_blocks_is_refilled_to_a_full_page_without_them(engine_client, engine, tmp_path, monkeypatch, route):
    restored = _restored("test_blocks", "test_an_upnext_page_stays_full_after_blocks_remove_rows_from_it", {"engine_client", "engine", "route"}, {"route": set(ROUTES)})
    with _own_client(tmp_path, engine, monkeypatch, "restored") as own:
        assert _outcome(restored, engine_client=own, engine=engine, route=route) is None  # C1
    # Without the pin the restored test is the archived one, which stayed green, vacuously in 6 of 12 trials (archive docstring); pinned and controlled, its limit-11 keyless page is no longer the pool's first 11.
    with _own_client(tmp_path, engine, monkeypatch, "unpinned") as own:
        assert isinstance(_outcome(restored, engine_client=_PinDropped(own), engine=engine, route=route), AssertionError), "the restored test passes when its up-next pages are not pinned"  # C1
    # The blocker's 16-row over-fetch is served all 11 pinned rows in keyless order, so a Client keeping blocked rows cuts to a page holding the 3 blocked ones.
    with _own_client(tmp_path, engine, monkeypatch, "unfiltered") as own, monkeypatch.context() as patch:
        patch.setattr(conftest.client_server, "filter_blocked", lambda rows, keys: rows)
        assert isinstance(_outcome(restored, engine_client=own, engine=engine, route=route), AssertionError), "the restored test passes on a Client that keeps blocked rows"  # C1
    # Cut to 8 first, the page holds the 3 blocked rows and the filter leaves 5.
    with _own_client(tmp_path, engine, monkeypatch, "unrefilled") as own, monkeypatch.context() as patch:
        patch.setattr(conftest.client_server, "_filter_payload", _cut_before_filter(conftest.client_server._filter_payload))
        assert isinstance(_outcome(restored, engine_client=own, engine=engine, route=route), AssertionError), "the restored test passes on a Client that does not refill from its over-fetch"  # C1

    client = engine_client
    seed = _search_rows(client, SEARCH)[0]
    chosen, pin = _pinned(engine, route, seed, STAYS_FULL)
    keyless = _upnext(client, route, seed, STAYS_FULL, None, pin)
    # Control: at limit 11 the keyless page is the 11 pinned rows whole, the very rows the blocker's over-fetch is served.
    assert _keys(keyless) == _keys(chosen), _keys(keyless)
    key = _mint(client)
    blocked = keyless[:3]
    for row in blocked:
        _block(client, key, "channel", row)

    rows = _upnext(client, route, seed, PAGE, key, pin)
    assert len(rows) == PAGE, len(rows)  # C1
    assert not {_channel(r) for r in blocked} & {_channel(r) for r in rows}  # C1
    # One row per channel in the pool, so the full page is exactly the other 8.
    assert _keys(rows) == _keys(keyless[3:])  # C1


# --- test_frontend_blocks.py: a channel blocked through blocks.ts, on the runner's pinned up-next fetch ---


def test_the_runner_s_pinned_upnext_fetch_holds_the_target_channel_before_a_module_block_and_leaves_it_out_after(engine_client, engine, tmp_path, monkeypatch):
    restored = _restored("test_frontend_blocks", "test_a_channel_blocked_through_the_module_leaves_the_upnext_and_search_rows_it_fetches", {"engine_client", "engine", "tmp_path"}, {})
    refused = _restored("test_frontend_blocks", "test_a_key_the_server_refuses_surfaces_as_profile_key_rejected_on_upnext_and_search", {"engine_client", "tmp_path"}, {})
    sent_pins: list[frozenset[tuple[str, str]] | None] = []
    with _own_client(tmp_path, engine, monkeypatch, "restored") as own:
        with monkeypatch.context() as patch:
            patch.setattr(conftest.client_server.ClientBackendHandler, "_proxy_engine_request", _recording_upnext(conftest.client_server.ClientBackendHandler._proxy_engine_request, sent_pins))
            assert _outcome(restored, engine_client=own, engine=engine, tmp_path=_workdir(tmp_path, "restored-run")) is None  # C2
        # Regression guard: the refused-key test, adapted to the new `_seed_and_targets`, still passes.
        assert _outcome(refused, engine_client=own, engine=engine, tmp_path=_workdir(tmp_path, "refused-run")) is None
    # Unfiltered, the blocked profile's limit-8 up-next fetch is served the 8 pinned rows whole, the target's channel included.
    with _own_client(tmp_path, engine, monkeypatch, "upnext-unfiltered") as own, monkeypatch.context() as patch:
        patch.setattr(conftest.client_server, "FILTERED_ROUTES", frozenset({SEARCH_PATH}))
        assert isinstance(_outcome(restored, engine_client=own, engine=engine, tmp_path=_workdir(tmp_path, "upnext-unfiltered-run")), AssertionError), "the restored test passes on a Client that does not filter up-next pages"  # C2
    with _own_client(tmp_path, engine, monkeypatch, "search-unfiltered") as own, monkeypatch.context() as patch:
        patch.setattr(conftest.client_server, "FILTERED_ROUTES", conftest.client_server.FEED_ROUTES)
        assert isinstance(_outcome(restored, engine_client=own, engine=engine, tmp_path=_workdir(tmp_path, "search-unfiltered-run")), AssertionError), "the restored test passes on a Client that does not filter search"  # C2

    frontend = importlib.import_module("test_frontend_blocks")
    client = engine_client
    search = _search_rows(client, FRONTEND_SEARCH)
    seed = search[0]
    chosen, pin = _pinned(engine, "/recommendations", seed, PAGE)
    # The restored run's node runner sent its keyed up-next fetches pinned to these same 8: a body that never passes `exclude` sends None, and an unpinned before page is a draw that may or may not hold its target.
    assert sent_pins and all(sent == _pin_keys(pin["exclude"]) for sent in sent_pins), [None if sent is None else len(sent) for sent in sent_pins]  # C2
    in_upnext = chosen[0]
    in_search = next(r for r in search if _channel(r) not in {_channel(c) for c in chosen})
    runner = frontend._bundle(_workdir(tmp_path, "direct"), client.base)
    out = frontend._run(runner, client.base, seed, [
        "create", "upnext", "search",
        f"block|{in_upnext['video_uuid']}|{in_upnext['instance_domain']}",
        f"block|{in_search['video_uuid']}|{in_search['instance_domain']}",
        "upnext", "search",
    ], exclude=pin["exclude"])
    _key, before_upnext, before_search, _b1, _b2, after_upnext, after_search = out

    # The pin reaches the Engine through the runner: a fresh profile's limit-8 fetch is the pool's first 8, served whole (an unpinned draw is 8 of a 32-row window).
    assert sorted(map(tuple, before_upnext["ok"])) == sorted(_channel(r) for r in chosen), before_upnext  # C2
    # Over-fetched to 16, the 8 pinned rows come back whole and the block takes out exactly the target's.
    assert sorted(map(tuple, after_upnext["ok"])) == sorted(_channel(r) for r in chosen[1:]), after_upnext  # C2
    assert list(_channel(in_search)) in before_search["ok"], before_search  # control: the search row's channel is fetched before its block
    assert after_search["ok"] and list(_channel(in_search)) not in after_search["ok"], after_search  # C2
