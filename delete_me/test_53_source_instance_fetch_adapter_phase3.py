"""Phase 3 checkpoint of plan 53: `/api/video` fetches the instance's video detail through `data.source_fetch`, so a detail answer that redirects off the instance or runs over the 2,000,000-byte cap is a failed detail call, answered from the stored row.

Three refused answers on the detail URL: a 302 to `https://cdn.example/api/v1/videos/uuid-1` (that URL is served the full source payload), a declared Content-Length of 2,000,001 over the source payload, and the source payload padded with JSON whitespace to 2,000,001 bytes. Each is paired with a control that differs in that one thing, served straight from the instance, by Content-Length 2,000,000, or padded to exactly 2,000,000 bytes.

- `video.fetch_instance_json` answers None for each refused answer, having opened only the detail URL, under a 4 s socket timeout; for each control it answers the source payload.
- `handle_video_request`, over test_video.py's seeded whitelist DB and writing through the real `respond_json` into test_internal_translate.py's `HandlerRequest`, answers 200 with the stored title, description, counts, tags, category, language, nsfw, duration, thumbnail, channel name and subscriber count, leaves the videos row, every channels row and `instances.last_error*` as they were, and opens only `(detail URL, 4)`, never the redirect target. The same server then writes the control's title to the row.
- Over HTTP, `/api/video` on a real `SimilarServer` in the Engine child answers 200 with test_video.py's DB-only body for each refused answer, leaves every videos, channels and instances row as seeded, and opens only the detail URL under a 4 s timeout; with the instance answering the detail and the channel it answers test_video.py's live body, writes the row's title and clears `instances.last_error`.

The network is severed at the adapter's single patch point, `data.source_fetch.build_opener`: in process with test_internal_translate.py's `ScriptedInstance` (a real urllib opener whose only fake part is the https open step), recording each `(full_url, timeout)`; in the Engine child with an inline scripted `HTTPSHandler` built the same way. Name resolution fails for any host but the child's loopback, so a fetch that goes around the adapter fails instead of reaching a real host.
"""
from __future__ import annotations

import importlib
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from conftest import ENGINE_PY  # noqa: E402
from test_internal_translate import Clock, HandlerRequest, Response, ScriptedInstance  # noqa: E402
from test_video import ANSWERING, API_DIR, CHANNEL_PATH, DB_ONLY, DETAIL, DETAIL_PATH, HOST, LIVE, NEWSLUG_PATH, OLD_CHECKED_AT, PARAMS, PEER_HOST, SOURCE, STORED_ANSWER, UUID, VIDEO_PATH, VIDEO_URL, _answered, _rows, _seed, _snapshot, _video, server, sync_job, video  # noqa: E402,F401

CDN_URL = "https://cdn.example/api/v1/videos/uuid-1"
NEWSLUG_URL = f"https://{PEER_HOST}{NEWSLUG_PATH}"
SOURCE_BYTES = json.dumps(SOURCE).encode("utf-8")


def _padded(size: int) -> bytes:
    """The source payload followed by JSON whitespace up to exactly size bytes, so it still parses to SOURCE."""
    return SOURCE_BYTES + b" " * (size - len(SOURCE_BYTES))


# (what the instance serves, the control that differs in one thing), as ScriptedInstance.serve keywords per URL.
REFUSED = {
    # The target is served the full payload, so a fetch that followed it would write "New title".
    "redirect off the instance": ({VIDEO_URL: {"status": 302, "headers": {"Location": CDN_URL}}, CDN_URL: {"chunks": [SOURCE_BYTES]}}, {VIDEO_URL: {"chunks": [SOURCE_BYTES]}}),
    # The body itself is small, so only the declared length can refuse it.
    "Content-Length 2,000,001": ({VIDEO_URL: {"headers": {"Content-Length": "2000001"}, "chunks": [SOURCE_BYTES]}}, {VIDEO_URL: {"headers": {"Content-Length": "2000000"}, "chunks": [SOURCE_BYTES]}}),
    "2,000,001 bytes streamed": ({VIDEO_URL: {"chunks": [_padded(2_000_001)]}}, {VIDEO_URL: {"chunks": [_padded(2_000_000)]}}),
}

# Engine child: each refused answer on tube.example's detail URL, with the channel served too, so a fetch that got past the adapter would write the live values.
DETAIL_URL = f"https://{HOST}{DETAIL_PATH}"
CDN_DETAIL_URL = f"https://cdn.example{DETAIL_PATH}"
CHANNEL_ROUTE = {f"https://{HOST}{CHANNEL_PATH}": {"json": ANSWERING[CHANNEL_PATH]}}
HTTP_REFUSED = {
    "redirect off the instance": {DETAIL_URL: {"status": 302, "headers": {"Location": CDN_DETAIL_URL}}, CDN_DETAIL_URL: {"json": DETAIL}, **CHANNEL_ROUTE},
    "Content-Length 2,000,001": {DETAIL_URL: {"headers": {"Content-Length": "2000001"}, "json": DETAIL}, **CHANNEL_ROUTE},
    "2,000,001 bytes streamed": {DETAIL_URL: {"json": DETAIL, "pad_to": 2_000_001}, **CHANNEL_ROUTE},
}
HTTP_ANSWERED = {DETAIL_URL: {"json": DETAIL}, **CHANNEL_ROUTE}

# Starts each case's server on its own DB, sends one /api/video GET with source_fetch.build_opener replaced by a scripted opener, and reports the status, the parsed body and every [host, selector, timeout] opened.
HTTP_CHILD = r'''
import http.client, inspect, io, json, socket, sys, threading
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.request import HTTPSHandler, build_opener
from urllib.response import addinfourl
import server
from data import source_fetch
from data.db import connect_db
from handlers.similar import SimilarHandler

real_getaddrinfo = socket.getaddrinfo
def loopback_only(host, *args, **kwargs):
    if host != "127.0.0.1":
        raise OSError("network severed by the checkpoint")
    return real_getaddrinfo(host, *args, **kwargs)
socket.getaddrinfo = loopback_only

reports = []
for db_path, path, routes in json.loads(sys.argv[1]):
    conn = connect_db(Path(db_path))
    args = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])
    srv = server.SimilarServer(("127.0.0.1", 0), SimilarHandler, **{**args, "db": conn, "video_error_threshold": 3, "popularity_like_weight": 2.0})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    calls = []
    class Scripted(HTTPSHandler):
        def https_open(self, req):
            calls.append([req.host, req.selector, req.timeout])
            route = routes.get(req.full_url, {"status": 404})
            body = json.dumps(route["json"]).encode("utf-8") if "json" in route else b""
            body += b" " * (route.get("pad_to", 0) - len(body))
            headers = Message()
            for name, value in route.get("headers", {}).items():
                headers[name] = value
            resp = addinfourl(io.BytesIO(body), headers, req.full_url, route.get("status", 200))
            resp.msg = "Scripted"
            return resp
    def opener(*handlers):
        return build_opener(Scripted(), *[handler for handler in handlers if not isinstance(handler, HTTPSHandler)])
    try:
        with patch.object(source_fetch, "build_opener", opener):
            client = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=30)
            client.request("GET", path)
            resp = client.getresponse()
            body = json.loads(resp.read() or b"null")
            client.close()
        reports.append({"status": resp.status, "body": body, "calls": calls})
    finally:
        srv.shutdown()
        srv.server_close()
        conn.close()
print(json.dumps(reports))
'''


class TimedInstance(ScriptedInstance):
    """The scripted instance, also recording each request as `(full_url, timeout)`, the contract of test_video.py's `_serve`."""

    def __init__(self, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(clock, monkeypatch)
        self.calls: list[tuple[str, object]] = []

    def open(self, req) -> Response:  # noqa: ANN001
        self.calls.append((req.full_url, req.timeout))
        return super().open(req)

    def serve_all(self, routes: dict[str, dict]) -> None:
        self.routes.clear()
        for url, keywords in routes.items():
            self.serve(url, **keywords)


@pytest.fixture
def instance(monkeypatch) -> TimedInstance:
    def unreachable(*args: object, **kwargs: object) -> list:
        raise OSError("network severed by the checkpoint")

    monkeypatch.setattr(socket, "getaddrinfo", unreachable)
    scripted = TimedInstance(Clock(), monkeypatch)
    monkeypatch.setattr(importlib.import_module("data.source_fetch"), "build_opener", scripted.build_opener)
    return scripted


@pytest.mark.parametrize("refused, control", REFUSED.values(), ids=REFUSED.keys())
def test_fetch_instance_json_answers_none_for_a_refused_detail_and_opens_only_the_detail_url(instance, refused, control):
    instance.serve_all(refused)
    assert video.fetch_instance_json(PEER_HOST, VIDEO_PATH) is None  # C1
    # Today's urlopen goes around the adapter and opens nothing here; following the redirect adds the cdn.example URL.
    assert instance.calls == [(VIDEO_URL, 4)]  # C1
    # Control: the answer that differs in that one thing comes back as the source payload.
    instance.serve_all(control)
    assert video.fetch_instance_json(PEER_HOST, VIDEO_PATH) == SOURCE  # C1: control
    assert instance.calls == [(VIDEO_URL, 4), (VIDEO_URL, 4)]  # C1: control


@pytest.mark.parametrize("refused, control", REFUSED.values(), ids=REFUSED.keys())
def test_api_video_answers_the_stored_row_and_writes_nothing_when_the_detail_is_refused(server, instance, refused, control):
    instance.serve_all(refused)
    before = _snapshot(server.db)
    assert before[2] == ("boom", 5, "video"), "the seeded instance error is what the comparison must preserve"
    handler = HandlerRequest({})

    video.handle_video_request(handler, server, PARAMS)

    # The redirect target is never requested: only the detail URL, under the adapter's 4 s socket timeout.
    assert instance.calls == [(VIDEO_URL, 4)]  # C1
    assert [status for status, _ in handler.responses] == [200]  # C1
    body = handler.responses[0][1]
    # A followed redirect or an uncapped read answers "New title", views 50 and the rest of SOURCE.
    assert _answered(body, STORED_ANSWER) == STORED_ANSWER  # C1
    assert body.get("nsfw", "MISSING") is False  # C1
    # A followed redirect or an uncapped read writes the row, the channel and clears instances.last_error.
    assert _snapshot(server.db) == before  # C1
    # Control: the same server, served the answer that differs in that one thing, writes the row.
    instance.serve_all(control)
    video.handle_video_request(handler, server, PARAMS)
    assert [(status, reply.get("title")) for status, reply in handler.responses] == [(200, "Old title"), (200, "New title")]  # C1: control
    stored = _video(server.db)
    assert (stored["title"], stored["last_checked_at"] > OLD_CHECKED_AT) == ("New title", True)  # C1: control
    assert instance.calls == [(VIDEO_URL, 4), (VIDEO_URL, 4), (NEWSLUG_URL, 4)]  # C1: control


@pytest.fixture(scope="module")
def http_reports(sync_job, tmp_path_factory) -> dict[str, dict]:
    """Every Engine-child case on its own freshly seeded DB in one child run: its report beside the rows before and after."""
    tmp = tmp_path_factory.mktemp("phase3_http")
    cases = {**HTTP_REFUSED, "answered": HTTP_ANSWERED}
    runs, before = [], {}
    for index, (name, routes) in enumerate(cases.items()):
        db_path = tmp / f"case{index}.db"
        _seed(sync_job, db_path)
        before[name] = _rows(db_path)
        runs.append([str(db_path), f"/api/video?id={UUID}&host={HOST}", routes])
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", HTTP_CHILD, json.dumps(runs)], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter built each server and ran every request
    reports = json.loads(run.stdout)
    return {name: {**report, "before": before[name], "after": _rows(Path(db_path))} for (name, (db_path, _, _)), report in zip(zip(cases, runs), reports)}


@pytest.mark.parametrize("case", HTTP_REFUSED.keys())
def test_api_video_over_http_answers_the_db_only_body_and_writes_nothing_when_the_detail_is_refused(http_reports, case):
    report = http_reports[case]
    # Today's urlopen goes around the adapter and opens nothing here; following the redirect adds the cdn.example detail and the channel.
    assert report["calls"] == [[HOST, DETAIL_PATH, 4]]  # C1
    # A followed redirect or an uncapped read answers LIVE's "Live title", views 1000 and the account avatar.
    assert (report["status"], report["body"]) == (200, DB_ONLY)  # C1
    # A followed redirect or an uncapped read bumps last_checked_at, rewrites the channel and clears instances.last_error 'boom'.
    assert report["after"] == report["before"]  # C1


def test_api_video_over_http_answers_the_live_body_through_the_same_opener(http_reports):
    # Control: the child's scripted opener is the route /api/video fetches by, so the DB-only answers above are the refusals' doing.
    report = http_reports["answered"]
    assert (report["status"], report["body"]) == (200, LIVE)  # C1: control
    assert report["calls"] == [[HOST, DETAIL_PATH, 4], [HOST, CHANNEL_PATH, 4]]  # C1: control
    # Control: the rows are read back from the DB the child served, so the unchanged rows above are the refusals' doing, not a write the comparison cannot see.
    assert [(rows["videos"]["v1"]["title"], rows["instances"][HOST]["last_error"]) for rows in (report["before"], report["after"])] == [("DB title", "boom"), ("Live title", None)]  # C1: control
