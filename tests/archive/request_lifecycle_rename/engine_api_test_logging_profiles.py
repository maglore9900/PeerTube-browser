"""Retired from `engine/server/api/tests/test_logging_profiles.py` in build 20-request-lifecycle-logs (plan 21), step 8, at the operator's direction.

All three conflict with that build's R9: the `[access.start]` → `access.start` and `[access]` → `access` rules are gone, replaced by `[request.start]` / `[request.end]` logged with a `structured_context` extra, and `request.end` carries only `{status, duration_ms}` (no url, no bytes).

- `test_access_start_is_tagged_for_focused_and_verbose` and `test_access_message_does_not_duplicate_context` assert the old events and messages for messages that now fall to `access.start.info` / `access.info`.
- `test_smoke_stream_contains_valid_json_events_with_modes` logs an `[access]` record and expects event `access`, visible in focused mode.

Plan 21's Tests section drafted their `request.start` / `request.end` rewrites; issue 39 tracks the replacement. The Engine names they use (`EngineJsonFormatter`, `payload_visible_in_mode`, `set_request_id`) are deliberately not imported here: importing them would put the Engine's `request_context` on the session's `sys.path`. Kept readable; skipped under pytest and unittest.
"""
from __future__ import annotations

import io
import json
import logging
import unittest

import pytest

pytestmark = pytest.mark.skip(reason="retired test, kept for reference")


@unittest.skip("retired test, kept for reference")
class EngineJsonFormatterTests(unittest.TestCase):
    """Validate JSON log formatting and mode-tag behavior."""

    def _format_record(self, level: int, message: str) -> dict[str, object]:
        """Format one log record into a structured JSON payload."""
        formatter = EngineJsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=level,
            pathname=__file__,
            lineno=1,
            msg=message,
            args=(),
            exc_info=None,
        )
        return json.loads(formatter.format(record))

    def test_access_start_is_tagged_for_focused_and_verbose(self) -> None:
        """Ensure request-start access lines are visible in both modes."""
        payload = self._format_record(
            logging.INFO,
            "[access.start] ip=127.0.0.1 method=POST url=http://127.0.0.1:7171/recommendations",
        )
        self.assertEqual(payload["event"], "access.start")
        self.assertEqual(payload["message"], "request started")
        self.assertIn("focused", payload["modes"])
        self.assertIn("verbose", payload["modes"])
        self.assertEqual(payload["context"]["method"], "POST")

    def test_access_message_does_not_duplicate_context(self) -> None:
        """Keep access message concise while details stay in context fields."""
        payload = self._format_record(
            logging.INFO,
            "[access] ip=127.0.0.1 method=POST url=http://127.0.0.1:7171/recommendations status=200 bytes=-",
        )
        self.assertEqual(payload["event"], "access")
        self.assertEqual(payload["message"], "request finished")
        self.assertEqual(payload["context"]["status"], "200")
        self.assertEqual(payload["context"]["url"], "http://127.0.0.1:7171/recommendations")

    def test_smoke_stream_contains_valid_json_events_with_modes(self) -> None:
        """Emit a mini request-flow stream and validate JSON + expected mode tags."""
        stream = io.StringIO()
        logger = logging.getLogger("test.engine.json")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = logging.StreamHandler(stream)
        handler.setFormatter(EngineJsonFormatter())
        logger.addHandler(handler)

        set_request_id("abc123")
        logger.info("[recommendations] layer timing: explore=10ms(2)")
        logger.info("[recommendations] profile=home likes=yes")
        logger.info("[recommendations] exploit cache seed batch ms=1 likes=2 resolved=2")
        logger.info("[similar-cache] hit source=1@host count=20 limit=1000")
        logger.info("[similar-server] candidates=13 limit=1000")
        logger.info("[access] ip=127.0.0.1 method=POST url=http://127.0.0.1:7171/ status=200 bytes=-")

        events = []
        for line in stream.getvalue().splitlines():
            payload = json.loads(line)
            events.append(payload["event"])
            self.assertIn("ts", payload)
            self.assertEqual(payload["request_id"], "abc123")
            self.assertTrue(payload_visible_in_mode(payload, "focused"))
            self.assertTrue(payload_visible_in_mode(payload, "verbose"))

        self.assertEqual(
            set(events),
            {
                "recommendations.layer_timing",
                "recommendations.profile",
                "recommendations.exploit_seed_batch",
                "similarity.cache_hit",
                "similarity.candidates",
                "access",
            },
        )
