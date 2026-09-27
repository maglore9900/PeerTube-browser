"""POST `/videos/similar` answers an oversized or malformed likes list with the 400 body `/recommendations` gives, and still serves a list of exactly `DEFAULT_CLIENT_LIKES_MAX` well-formed likes.

- `DEFAULT_CLIENT_LIKES_MAX + 1` likes, and each of a blank uuid at index 0, a non-object entry at index 0 and a non-string host at index 2, get exactly one `respond_json(handler, 400, body)`, whose body is written out literally and equals the one `/recommendations` gives for the same likes. The likes are then never parsed, `set_request_client_likes` is never called, the request context is not cleared and the request is not handled.
- `DEFAULT_CLIENT_LIKES_MAX` well-formed likes get no response from the likes check: `_parse_client_likes` runs once on the body, its entries are resolved, the likes are set on the request context and the request is handled.

`similar.SimilarHandler._handle_similar_request(handler, method="POST")` runs on `_DummySimilarHandler` from `engine/server/api/tests/test_recommendations_likes_limit.py`, inside the Engine's interpreter, with the body reader, the responder, the request-context setters and the DB lookup of likes patched. `_parse_client_likes` and `_recommendations_likes_payload_error` run for real.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import server_config  # noqa: E402

# The interpreter `tests/active/conftest.py` starts the Engine with; pytest's own has no numpy, so it cannot import handlers.similar (observed).
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
LIKES_MAX = server_config.DEFAULT_CLIENT_LIKES_MAX
# What the patched `_resolve_client_likes` returns: non-empty and unlike the handler's default `[]`, so only the resolved value reaching `set_request_client_likes` matches it.
RESOLVED_LIKES = [{"video_uuid": "resolved-sentinel", "instance_domain": "resolved.example"}]
# Runs each (path, body) case through the real `_handle_similar_request` and reports every call it made at the patched boundaries.
HANDLE_CASES = r'''
import json, sys
from unittest.mock import patch
sys.path[:0] = sys.argv[1:4]
from handlers import similar
from test_recommendations_likes_limit import _DummySimilarHandler
resolved = json.loads(sys.argv[5])
reports = []
for path, body in json.loads(sys.argv[4]):
    handler = _DummySimilarHandler(path)
    with (
        patch.object(similar, "read_json_body", return_value=body),
        patch.object(similar, "respond_json") as respond,
        patch.object(similar, "_parse_client_likes", wraps=similar._parse_client_likes) as parse,
        patch.object(similar, "_resolve_client_likes", return_value=resolved) as resolve,
        patch.object(similar, "set_request_client_likes") as set_likes,
        patch.object(similar, "clear_request_context") as clear,
    ):
        similar.SimilarHandler._handle_similar_request(handler, method="POST")
    reports.append({
        "likes_max": similar.DEFAULT_CLIENT_LIKES_MAX,
        "respond": [[c.args[0] is handler, *c.args[1:]] for c in respond.call_args_list],
        "parse": [c.args[0] for c in parse.call_args_list],
        "resolve": [[c.args[0] is handler.server, c.args[1]] for c in resolve.call_args_list],
        "set_likes": [list(c.args) for c in set_likes.call_args_list],
        "clear": clear.call_count,
        "handled": handler.handled,
    })
print(json.dumps(reports))
'''


def _handle(*cases: tuple[str, dict]) -> list[dict]:
    run = subprocess.run([str(ENGINE_PY), "-c", HANDLE_CASES, str(SERVER_DIR), str(API_DIR), str(API_DIR / "tests"), json.dumps(cases), json.dumps(RESOLVED_LIKES)], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter imported the handler and ran every case
    return json.loads(run.stdout)


def _likes(count: int) -> list[dict]:
    return [{"uuid": f"video-{idx}", "host": "example.com"} for idx in range(count)]


def _rejected(body: dict) -> dict:
    # A request the likes check stops: one 400 to this handler, and nothing past it runs.
    return {"likes_max": LIKES_MAX, "respond": [[True, 400, body]], "parse": [], "resolve": [], "set_likes": [], "clear": 0, "handled": False}


class VideosSimilarLikesLimitTests(unittest.TestCase):
    """Validate the `/recommendations` likes 400 contract on `/videos/similar`."""

    def test_videos_similar_rejects_more_likes_than_allowed(self) -> None:
        """Return the `/recommendations` 400 body when likes exceed the configured max."""
        body = {"likes": _likes(LIKES_MAX + 1)}
        similar_report, recommendations_report = _handle(("/videos/similar", body), ("/recommendations", body))

        expected = _rejected({"error": "Too many likes in request body", "max_allowed": LIKES_MAX, "received": LIKES_MAX + 1})
        self.assertEqual(recommendations_report, expected)  # control: the body `/recommendations` gives today (observed)
        self.assertEqual(similar_report, expected)  # C1: one 400 with that exact body, likes never parsed or set, request not handled
        self.assertEqual(similar_report, recommendations_report)  # C1: the same as `/recommendations` for the same likes

    def test_videos_similar_rejects_invalid_likes_item_format(self) -> None:
        """Return the `/recommendations` 400 body for a malformed likes entry, naming its reason and index."""
        cases = {
            "blank uuid": ([{"uuid": "   ", "host": "example.com"}], "likes.uuid must be a non-empty string", 0),
            "non-object entry": (["video-0"], "likes entry must be an object", 0),
            "non-string host after two valid": ([*_likes(2), {"uuid": "video-2", "host": 7}], "likes.host must be a non-empty string", 2),
        }
        reports = _handle(*[(path, {"likes": likes}) for likes, _, _ in cases.values() for path in ("/videos/similar", "/recommendations")])
        for (name, (_, reason, index)), similar_report, recommendations_report in zip(cases.items(), reports[0::2], reports[1::2]):
            with self.subTest(name):
                expected = _rejected({"error": "Invalid likes payload", "reason": reason, "index": index})
                self.assertEqual(recommendations_report, expected)  # control: the body `/recommendations` gives today (observed)
                self.assertEqual(similar_report, expected)  # C1: one 400 with that exact body, likes never parsed or set, request not handled
                self.assertEqual(similar_report, recommendations_report)  # C1: the same as `/recommendations` for the same likes

    def test_videos_similar_allows_likes_at_limit(self) -> None:
        """Keep the existing flow when the likes count equals the allowed maximum."""
        body = {"likes": _likes(LIKES_MAX)}
        (report,) = _handle(("/videos/similar", body))

        self.assertEqual(report["likes_max"], LIKES_MAX)  # control: the handler checks against the same max this test sends
        self.assertEqual(report["respond"], [])  # C2: no 400, nor any other response from the likes check
        self.assertEqual(report["parse"], [body])  # C2: `_parse_client_likes` runs once, on the body
        self.assertEqual(report["resolve"], [[True, [{"video_uuid": f"video-{idx}", "instance_domain": "example.com"} for idx in range(LIKES_MAX)]]])  # C2: every like reaches resolution
        self.assertEqual(report["set_likes"], [[RESOLVED_LIKES, True]])  # C2: what resolution returned, not the default `[]`, is set on the request context
        self.assertEqual(report["clear"], 1)  # C2
        self.assertTrue(report["handled"])  # C2: the request is handled


if __name__ == "__main__":
    unittest.main()
