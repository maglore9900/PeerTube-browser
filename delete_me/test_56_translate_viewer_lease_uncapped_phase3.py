"""Plan 56 phase 3 checkpoint: a state read renews a leased queued or running job's viewer lease and writes no other row, and a cancel through the Client gateway reaches the started Engine's cancel route and caps the lease at the grace without ever lengthening it, answering the state and available; the page's data layer posts its cancel to that gateway route.

Renewal (`handle_internal_translate` through the harness of tests/active/test_internal_translate.py, `now_ms` pinned at NOW, a fresh beat): v-1 seeded leased queued, leased running, ready carrying a stale lease, failed carrying it, already_english carrying it, unleased queued, or with no row, beside three other keys (another host, another video, another language) each queued with the same stale lease. Each answers exactly what the route answered before this phase (observed on the unchanged route). The leased queued and running rows end with `wanted_at` NOW and every other column, rowid included, as before; the ready, failed, already_english and unleased rows are byte-identical; the missing key still has no row; the other keys' rows are byte-identical in every case.

Cancel at the Engine (`handle_internal_translate_cancel`, same harness): a leased queued row with a fresh lease, one 1 ms after the cap, and a leased running row end with `wanted_at` NOW - 160 000 (the 180 s lease less the 20 s grace); a lease 1 ms before the cap keeps its value; an unleased queued row and a ready, failed or already_english row carrying a fresh lease keep theirs; a missing key gets no row. Each answers exactly `{state, available}`: the stored state (none for no row), no cues, available true under a fresh beat and false with no beat.

Cancel through the gateway to the started Engine (server.py started as tests/active/test_internal_translate.py starts it, on the repo's whitelist.db and a fresh subtitles.db; the real Client backend over it): a video the whitelist resolves, queued with a lease taken after the start, answers `POST /api/translate/cancel` with a valid profile `{queued, false}` and ends with `wanted_at` between the request's send and answer times less 160 000, every other column as before; the Engine's `/internal/translate/cancel` without the bridge token answers 401 and leaves the row as it was.

Cancel through the gateway (the real Client backend over a routed stub Engine): `POST /api/translate/cancel` with a valid profile makes exactly one bridge call, to `/internal/translate/cancel` with the bridge token, the request id and exactly `{id, host}`, and answers the Engine's `{state, available}` (queued/true, running/false), or `{none, false}` for its 404 `Video not found`; without a profile it answers 401 and calls nothing.

Contract (tests/active/fixtures/translate_contract.json): the cancel route's valid 200 states, with and without available, are exactly the six stored states; it has exactly one 404 `Video not found` case, answered `{none, false}`, and rejected cases for busy, an unknown state, a route-missing 404 and available as a string; no cancel case carries cues. Every cancel case replays through `lib.engine_api_client.cancel_translate` (its gateway answer, or EngineApiError "Engine translate ..." where rejected, from one POST of `{id, host}` to /internal/translate/cancel) and through `cancelTranslate` in data/translate.ts bundled alone and run in node, which is first served a queued answer and a busy one directly (queued/true and "Translate response was malformed"; its gateway answer, or exactly "Translate response was malformed" where rejected, from one POST of `{id, host}` to /api/translate/cancel). The Engine drivers cover exactly the fixture's (route, state) pairs, and each cancel pair driven through the real cancel handler answers one 200 in that state with the case's key-to-JSON-type map.
"""
from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from test_internal_translate import BODY, BRIDGE_TOKEN, CONTRACT, ENGINE_DRIVERS, ENGINE_PY, ENGINE_SERVER, ENGINE_START_LOCK, HANDLERS, HEALTHY_WITHIN_SECONDS, HOST, NOW, RUNNING, STOP_WITHIN_SECONDS, STORED_READY, VARIANT_RUNNER, VIDEO_ID, _beat, _engine_cases, _free_port, _instance, _post, _record_handlers, _request, _route, _server, _state, _subtitles_db, _types, whitelist  # noqa: E402,F401
from test_server import TRANSLATE_BRIDGE_TOKEN, TRANSLATE_UNAUTHORIZED, _keyed_client_backend, _routed_translate_engine, _translate_engine, translate_bridge_token  # noqa: E402,F401
from conftest import WHITELIST_DB, RateLimiter  # noqa: E402

from data.subtitles import claim_translate_job, enqueue_translate_job, store_ready_subtitles  # noqa: E402
from lib.engine_api_client import EngineApiError  # noqa: E402

# A lease the route has not written: a minute old, so a row the read did not renew still reads it, not NOW.
LEASE = NOW - 60_000
# The settled design's cap, now - TRANSLATE_LEASE_MS (180 000) + TRANSLATE_CANCEL_GRACE_MS (20 000), written down rather than computed from the constants.
CAPPED = NOW - 160_000
FRESH = NOW - 1_000
STORED_STATES = {"none", "queued", "running", "ready", "already_english", "failed"}
CANCEL_ROUTE = "/internal/translate/cancel"
GATEWAY_CANCEL = "/api/translate/cancel"
GATEWAY_BODY = {"id": "uuid-1", "host": "peer.example"}
MALFORMED = "Translate response was malformed"
# v-1's subtitles key, and one key differing from it in each part, so a renewal missing any part of its key filter writes one of them.
KEY = (VIDEO_ID, HOST, "en")
OTHER_KEYS = ((VIDEO_ID, "other.example", "en"), ("v-2", HOST, "en"), (VIDEO_ID, HOST, "fr"))

# Seeded row -> (state, its lease or None unleased, the answer the unchanged route gave, observed by probe on the pre-phase handler with a fresh beat).
RENEWAL = {
    "leased queued": ("queued", LEASE, [[200, {"state": "queued", "available": True}]]),
    "leased running": ("running", LEASE, [[200, {"state": "running", "cues": RUNNING, "total": 3, "available": True}]]),
    "ready with a stale lease": ("ready", LEASE, [[200, {"state": "ready", "cues": STORED_READY, "available": True}]]),
    "failed with a stale lease": ("failed", LEASE, [[200, {"state": "failed", "available": True}]]),
    "already_english with a stale lease": ("already_english", LEASE, [[200, {"state": "already_english", "available": True}]]),
    "unleased queued": ("queued", None, [[200, {"state": "queued", "available": True}]]),
    "no row": (None, None, [[200, {"state": "none", "available": True}]]),
}
RENEWED = {"leased queued", "leased running"}
# The rows the unchanged route still looks up on the instance (observed by probe): failed, already_english and no row.
FETCHED = {"failed with a stale lease", "already_english with a stale lease", "no row"}

# Seeded row -> (state, lease, the lease the cancel must leave).
CANCEL = {
    "leased queued, fresh lease": ("queued", FRESH, CAPPED),
    "leased queued, lease 1 ms after the cap": ("queued", CAPPED + 1, CAPPED),
    "leased running, fresh lease": ("running", FRESH, CAPPED),
    "leased queued, lease 1 ms before the cap": ("queued", CAPPED - 1, CAPPED - 1),
    "unleased queued": ("queued", None, None),
    "ready carrying a fresh lease": ("ready", FRESH, FRESH),
    "failed carrying a fresh lease": ("failed", FRESH, FRESH),
    "already_english carrying a fresh lease": ("already_english", FRESH, FRESH),
}

# What the cancel route answers -> what the page gets through the gateway.
GATEWAY_ANSWERS = {
    "queued, available": ((200, {"state": "queued", "available": True}), (200, {"state": "queued", "available": True})),
    "running, not available": ((200, {"state": "running", "available": False}), (200, {"state": "running", "available": False})),
    "video not found": ((404, {"error": "Video not found"}), (200, {"state": "none", "available": False})),
}
# The other two routes answer something else, so a cancel sent there would show in the answer as well as in the log.
OTHER_ROUTES = {"/internal/translate": (200, {"state": "ready", "cues": [{"start": 1.0, "end": 2.0, "text": "Hello"}], "available": True}), "/internal/translate/enqueue": (200, {"state": "busy", "available": True})}

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
FRONTEND_BASE = "http://client.test"
# Served straight to cancelTranslate, so its parse is measured whatever the fixture holds: a valid answer, and busy, which requestTranslate accepts and a cancel never answers.
DIRECT = {"direct: queued, available": {"state": "queued", "available": True}, "direct: busy": {"state": "busy", "available": True}}
# Serves each DIRECT body, then each cancel case, as a 200 to cancelTranslate (a case's gateway answer when valid, its Engine body when rejected); records each request's method, path and body.
CANCEL_RUNNER = """
import { readFileSync } from "node:fs";
const memory = () => { const s = new Map(); return { getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)), removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
// api-base.ts reads window.location.origin when it is evaluated, so window exists before the import below.
globalThis.window = { location: { origin: process.env.BASE }, localStorage: globalThis.localStorage };
const asked = [];
let served = null;
globalThis.fetch = async (input, init) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  asked.push({ method: String(init?.method ?? "GET").toUpperCase(), path: url.pathname, body: init?.body == null ? null : JSON.parse(init.body) });
  return new Response(served, { status: 200, headers: { "content-type": "application/json" } });
};
const { cancelTranslate } = await import(process.env.BUNDLE);
const report = {};
const direct = Object.entries(JSON.parse(process.env.DIRECT)).map(([name, body]) => ({ name, body }));
const contract = JSON.parse(readFileSync(process.env.CONTRACT, "utf8")).cases.filter((c) => c.route === "cancel").map((c) => ({ name: c.name, body: c.gateway === "rejected" ? c.engine.body : c.gateway }));
for (const c of [...direct, ...contract]) {
  served = JSON.stringify(c.body);
  const before = asked.length;
  try {
    report[c.name] = { value: await cancelTranslate(process.env.BASE, "uuid-1", "peer.example") };
  } catch (error) {
    report[c.name] = { thrown: String(error?.message ?? error) };
  }
  report[c.name].asked = asked.slice(before);
}
process.stdout.write(JSON.stringify(report) + "\\n", () => process.exit(0));
"""


def _rows(path: Path) -> dict[str, dict]:
    """Every subtitles row, rowid included, keyed by video_id, through a fresh plain connection."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return {(row["video_id"], row["instance_domain"], row["target_language"]): dict(row) for row in conn.execute("SELECT rowid, * FROM subtitles")}
    finally:
        conn.close()


def _seed_key(path: Path, state: str | None, lease: int | None, beat: bool = True) -> None:
    """Leave v-1 in state through the store's own writers, queued with lease as the Engine route queues it (None queues as the CLI does, with no wanted_at); a ready row keeps the lease the instance-track store leaves behind, and a failed or already_english row the one its job ended with. A fresh beat unless beat is False."""
    store = _subtitles_db(path)
    if state is not None:
        extra = {} if lease is None else {"wanted_at": lease}
        assert enqueue_translate_job(store, VIDEO_ID, HOST, "en", 50, NOW - 2000, **extra) == ("queued", "queued")
    job = claim_translate_job(store, "en", NOW - 1000) if state in ("running", "failed", "already_english") else None
    if state == "running":
        assert job.write_running_cues(RUNNING, "fr")
    elif state == "failed":
        assert job.end_failed("boom", NOW - 500)
    elif state == "already_english":
        assert job.end_already_english("en", NOW - 500)
    elif state == "ready":
        store_ready_subtitles(store, VIDEO_ID, HOST, "en", "instance", "WEBVTT stored", STORED_READY, NOW - 1000)
    store.close()
    if beat:
        _beat(path, 0)


def _seed_others(path: Path) -> None:
    """Queue each of OTHER_KEYS with the stale lease, as other viewers' pages leave them; after v-1, so v-1 is the job a running seed claimed."""
    store = _subtitles_db(path)
    for video_id, host, language in OTHER_KEYS:
        assert enqueue_translate_job(store, video_id, host, language, 50, NOW - 1500, wanted_at=LEASE) == ("queued", "queued")
    store.close()


def _cancel(module, server, body: dict) -> list[list]:
    request = _request(body)
    module.handle_internal_translate_cancel(request, server)
    return request.responses


@pytest.mark.parametrize("name", RENEWAL)
def test_a_state_read_renews_only_a_leased_queued_or_running_row_to_now_and_answers_as_before(tmp_path, whitelist, monkeypatch, name):
    state, lease, answer = RENEWAL[name]
    path = tmp_path / "subtitles.db"
    _seed_key(path, state, lease)
    _seed_others(path)
    before = _rows(path)
    assert {key: row["wanted_at"] for key, row in before.items()} == {**dict.fromkeys(OTHER_KEYS, LEASE), **({KEY: lease} if state else {})}  # control: every lease as seeded, never NOW, so an unrenewed row reads differently
    assert before.get(KEY, {}).get("state") == state  # control: v-1 seeded in the state named
    instance = _instance(False)

    answered = _state(_route(instance, monkeypatch), _server(whitelist, path), BODY)

    after = _rows(path)
    assert answered == answer  # C1: the read result is the one the route gave before renewal existed
    if name in RENEWED:
        assert after == {**before, KEY: {**before[KEY], "wanted_at": NOW}}, (before, after)  # C1: v-1's lease is renewed to now, nothing else in its row (rowid included) moved, and the other keys' leased queued rows are unwritten
    else:
        assert after == before, (before, after)  # C1: a ready, failed, already_english, unleased or missing v-1 is left unwritten, no row appears for the missing key, and the other keys' rows are unwritten
    assert instance.fetched == ([("peer.example", "/api/v1/videos/u-1/captions")] if name in FETCHED else [])  # control: queued, running and ready answered from the store, the rest looked up on the instance, as before


@pytest.mark.parametrize("name", CANCEL)
def test_the_engine_cancel_caps_a_leased_queued_or_running_lease_at_now_less_160_s_never_lengthens_one_and_answers_the_stored_state(tmp_path, whitelist, monkeypatch, name):
    state, lease, capped = CANCEL[name]
    path = tmp_path / "subtitles.db"
    _seed_key(path, state, lease)
    before = _rows(path)
    assert before[KEY]["wanted_at"] == lease and before[KEY]["state"] == state  # control: seeded as named

    answered = _cancel(_route(_instance(False), monkeypatch), _server(whitelist, path), BODY)

    assert _rows(path) == {KEY: {**before[KEY], "wanted_at": capped}}, before  # C2: shortened to the cap, or kept where it is already earlier, unleased or not queued/running; no other column moved
    assert answered == [[200, {"state": state, "available": True}]]  # C2: the stored state with available, and no cues


def test_the_engine_cancel_of_a_key_with_no_row_writes_nothing_and_answers_none(tmp_path, whitelist, monkeypatch):
    path = tmp_path / "subtitles.db"
    _seed_key(path, None, None)
    answered = _cancel(_route(_instance(False), monkeypatch), _server(whitelist, path), BODY)
    assert answered == [[200, {"state": "none", "available": True}]]  # C2: none for no row
    assert _rows(path) == {}  # C2: the cancel creates no row


def test_the_engine_cancel_answers_available_false_with_no_worker_beat_and_still_caps_the_lease(tmp_path, whitelist, monkeypatch):
    path = tmp_path / "subtitles.db"
    _seed_key(path, "queued", FRESH, beat=False)
    answered = _cancel(_route(_instance(False), monkeypatch), _server(whitelist, path), BODY)
    assert answered == [[200, {"state": "queued", "available": False}]]  # C2: available is the heartbeat gate, not a constant
    assert _rows(path)[KEY]["wanted_at"] == CAPPED  # C2: the cap is not gated on a serving worker


def _cancel_post(base: str, body: dict, headers: dict[str, str]) -> tuple[int, object]:
    req = urllib.request.Request(base + GATEWAY_CANCEL, data=json.dumps(body).encode("utf-8"), method="POST", headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


@pytest.mark.parametrize("engine_reply, expected", GATEWAY_ANSWERS.values(), ids=GATEWAY_ANSWERS.keys())
def test_the_gateway_cancel_makes_one_bridge_call_to_the_engine_cancel_route_and_answers_its_state_and_available(tmp_path, translate_bridge_token, engine_reply, expected):
    replies = {**OTHER_ROUTES, CANCEL_ROUTE: engine_reply}
    with _routed_translate_engine(replies) as (engine_base, seen), _keyed_client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):
        keyless = _cancel_post(base, GATEWAY_BODY, {})
        keyless_seen = list(seen)
        answered = _cancel_post(base, GATEWAY_BODY, {**key, "X-Request-ID": "cancel-1"})
    assert answered == expected  # C2: the Engine cancel route's {state, available}, mapped for the page
    assert seen == [("POST", CANCEL_ROUTE, TRANSLATE_BRIDGE_TOKEN, "cancel-1", GATEWAY_BODY)]  # C2: exactly one bridge call, to the cancel route, with the token, the request id and exactly {id, host}
    assert keyless == TRANSLATE_UNAUTHORIZED and keyless_seen == []  # C2: only a valid profile reaches the Engine


def _whitelisted_video() -> tuple[str, str, str]:
    """A (video_id, video_uuid, instance_domain) the repo's whitelist.db holds with no fetch error on a host not actively denied, read through a read-only connection."""
    conn = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT video_id, video_uuid, instance_domain FROM videos WHERE COALESCE(error_count, 0) = 0 AND lower(instance_domain) NOT IN (SELECT lower(host) FROM instance_denylist WHERE is_active = 1) ORDER BY video_id LIMIT 1").fetchone()
    finally:
        conn.close()
    assert row is not None, f"{WHITELIST_DB} holds no video to cancel"
    return row


@contextmanager
def _started_engine(subtitles_path: Path, log_path: Path) -> Iterator[str]:
    """server.py started as the startup test of tests/active/test_internal_translate.py starts it, with its subtitles.db at subtitles_path and the bridge token set; yields its base URL."""
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": BRIDGE_TOKEN}
    with open(log_path, "w") as log:
        with open(ENGINE_START_LOCK, "w") as start_lock:
            fcntl.flock(start_lock, fcntl.LOCK_EX)
            proc = subprocess.Popen([str(ENGINE_PY), "-c", VARIANT_RUNNER, str(ENGINE_SERVER), json.dumps({"DEFAULT_SUBTITLES_DB_PATH": str(subtitles_path)}), "--host", "127.0.0.1", "--port", str(port), "--no-random-cache-refresh"], env=env, stdout=log, stderr=log)
            healthy = False
            deadline = time.time() + HEALTHY_WITHIN_SECONDS
            while proc.poll() is None and time.time() < deadline and not healthy:
                try:
                    with urllib.request.urlopen(base + "/api/health", timeout=5) as resp:
                        healthy = resp.status == 200
                except OSError:
                    time.sleep(0.1)
    try:
        assert healthy, f"the variant Engine did not answer /api/health 200 within {HEALTHY_WITHIN_SECONDS}s (exit {proc.poll()}); see {log_path}"
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=STOP_WITHIN_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def test_a_cancel_through_the_client_gateway_reaches_the_started_engines_cancel_route_and_caps_the_lease(tmp_path, translate_bridge_token):
    video_id, uuid, host = _whitelisted_video()
    key = (video_id, host, "en")
    body = {"id": uuid, "host": host}
    path = tmp_path / "subtitles.db"
    with _started_engine(path, tmp_path / "engine.log") as engine_base:
        # Leased after the start, so the lease is seconds old and the cap, 160 s back, is always earlier: only a real cap moves it.
        store = _subtitles_db(path)
        leased_at = int(time.time() * 1000)
        assert enqueue_translate_job(store, video_id, host, "en", 50, leased_at, wanted_at=leased_at) == ("queued", "queued")
        store.close()
        assert _post(engine_base, "/internal/translate", body, {"X-Bridge-Token": BRIDGE_TOKEN}) == (200, {"state": "queued", "available": False})  # control: the started Engine resolves this video and reads its row from this store
        before = _rows(path)
        tokenless = _post(engine_base, CANCEL_ROUTE, body, {})
        tokenless_rows = _rows(path)
        with _keyed_client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, profile):
            sent_at = int(time.time() * 1000)
            answered = _cancel_post(base, body, profile)
            answered_at = int(time.time() * 1000)
        after = _rows(path)
    assert answered == (200, {"state": "queued", "available": False})  # C2: the Engine cancel route's state and available, through the gateway
    assert sent_at - 160_000 <= after[key]["wanted_at"] <= answered_at - 160_000, (sent_at, answered_at, after)  # C2: the Engine's cancel route capped the lease at its now less 160 s while the request was in flight
    assert after == {key: {**before[key], "wanted_at": after[key]["wanted_at"]}}, (before, after)  # C2: nothing else in the row (rowid included) moved
    assert tokenless == (401, {"error": "Unauthorized"}) and tokenless_rows == before  # C2: the cancel route is behind the bridge gate and writes nothing without the token


def _cancel_cases() -> list[dict]:
    return [case for case in json.loads(CONTRACT.read_text())["cases"] if case["route"] == "cancel"]


def test_the_contract_states_the_cancel_route_as_the_six_stored_states_one_video_not_found_and_its_refusals():
    cases = _cancel_cases()
    valid = [case for case in cases if case["gateway"] != "rejected" and case["engine"]["status"] == 200]
    assert {case["engine"]["body"]["state"] for case in valid if "available" in case["engine"]["body"]} == STORED_STATES  # C2: with available, exactly the stored states
    assert {case["engine"]["body"]["state"] for case in valid if "available" not in case["engine"]["body"]} == STORED_STATES  # C2: without available, the same
    assert [case["gateway"] for case in cases if case["engine"] == {"status": 404, "body": {"error": "Video not found"}}] == [{"state": "none", "available": False}]  # C2: exactly one Video not found, read as none
    assert all(set(case["gateway"]) == {"state", "available"} for case in valid), valid  # C2: a valid cancel answers the page exactly state and available
    assert [case["name"] for case in cases if "cues" in case["engine"]["body"]] == []  # C2: no cancel case, valid or rejected, carries cues
    rejected = [case["engine"] for case in cases if case["gateway"] == "rejected"]
    assert any(engine["status"] == 200 and engine["body"].get("state") == "busy" for engine in rejected), rejected  # C2: busy is refused on cancel
    assert any(engine["status"] == 200 and engine["body"].get("state") not in STORED_STATES | {"busy"} for engine in rejected), rejected  # C2: so is an unknown state
    assert any(engine == {"status": 404, "body": {"error": "Not found"}} for engine in rejected), rejected  # C2: and an Engine without the route
    assert any(isinstance(engine["body"].get("available"), str) for engine in rejected), rejected  # C2: and available as a string


def test_every_cancel_contract_case_parses_through_the_gateway_cancel_translate_from_one_post_to_the_engine_cancel_route():
    from lib.engine_api_client import cancel_translate

    cases = _cancel_cases()
    assert cases  # control: the fixture carries cancel cases
    for case in cases:
        with _translate_engine((case["engine"]["status"], case["engine"]["body"])) as (engine_base, seen):
            if case["gateway"] == "rejected":
                with pytest.raises(EngineApiError, match=r"^Engine translate"):
                    cancel_translate(engine_base, "uuid-1", "peer.example")
            else:
                assert cancel_translate(engine_base, "uuid-1", "peer.example") == case["gateway"], case["name"]  # C2: the gateway's stated answer
        assert [(entry[0], entry[1], entry[4]) for entry in seen] == [("POST", CANCEL_ROUTE, GATEWAY_BODY)], case["name"]  # C2: one POST of {id, host} to the cancel route


def test_every_cancel_contract_case_parses_through_the_page_data_layer_cancel_translate_from_one_post_to_the_gateway_cancel_route(tmp_path):
    cases = _cancel_cases()
    subprocess.run([str(ESBUILD), str(FRONTEND / "src" / "data" / "translate.ts"), "--bundle", "--format=esm", "--platform=node", f"--outfile={tmp_path / 'bundle.mjs'}", f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(FRONTEND_BASE)}", "--define:import.meta.env.DEV=false"], check=True, capture_output=True)
    (tmp_path / "runner.mjs").write_text(CANCEL_RUNNER)
    proc = subprocess.run(["node", str(tmp_path / "runner.mjs")], capture_output=True, text=True, timeout=60, env={"BASE": FRONTEND_BASE, "BUNDLE": str(tmp_path / "bundle.mjs"), "CONTRACT": str(CONTRACT), "DIRECT": json.dumps(DIRECT), "PATH": os.environ.get("PATH", "")})
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout.splitlines()[-1])
    asked = [{"method": "POST", "path": GATEWAY_CANCEL, "body": GATEWAY_BODY}]
    assert report["direct: queued, available"] == {"value": {"state": "queued", "available": True}, "asked": asked}  # C2: one POST of {id, host} to the gateway cancel route, answered as its state and available
    assert report["direct: busy"] == {"thrown": MALFORMED, "asked": asked}  # C2: busy, which the request route answers, is refused on cancel
    assert cases  # control: the fixture carries cancel cases, so the replay below is not vacuous
    for case in cases:
        result = report[case["name"]]
        if case["gateway"] == "rejected":
            assert result.get("thrown") == MALFORMED, (case["name"], result)  # C2: refused by the page's parser, not by a JSON or gateway error
        else:
            assert result.get("value") == case["gateway"], (case["name"], result)  # C2: exactly the gateway answer
        assert result["asked"] == asked, (case["name"], result)  # C2: one POST of {id, host} to the gateway cancel route


def test_the_engine_drivers_cover_exactly_the_contract_pairs_and_each_cancel_state_answers_its_case_shape_from_the_real_cancel_handler(tmp_path, whitelist, monkeypatch):
    fixture = {(case["route"], case["engine"]["body"]["state"]) for case in _engine_cases()}
    assert {pair for pair in fixture if pair[0] == "cancel"} == {("cancel", state) for state in STORED_STATES}  # C2: the fixture's cancel pairs are the six stored states
    assert fixture == set(ENGINE_DRIVERS)  # C2: the exact-set check, a driver for every fixture pair and none without one
    assert HANDLERS.get("cancel") == "handle_internal_translate_cancel"  # control: the recorder below wraps the real cancel handler
    calls = _record_handlers(monkeypatch)
    for index, case in enumerate(case for case in _engine_cases() if case["route"] == "cancel"):
        calls.clear()
        responses = ENGINE_DRIVERS[("cancel", case["engine"]["body"]["state"])](tmp_path / f"subtitles-{index}.db", whitelist, monkeypatch, case)
        assert [(called, written) for called, _, written in calls] == [("cancel", responses)], case["name"]  # control: the cancel handler alone answered, and the driver returned what it wrote
        ((status, answer),) = responses
        assert (status, answer["state"]) == (200, case["engine"]["body"]["state"]), (case["name"], answer)  # C2: the driver reached the state under test
        assert _types(answer) == _types(case["engine"]["body"]), (case["name"], answer)  # C2: exactly the case's keys and JSON types
