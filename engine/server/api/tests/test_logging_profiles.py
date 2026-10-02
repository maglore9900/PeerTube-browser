"""Tests for structured engine logging helpers."""

from __future__ import annotations

import json
import logging
import sys
import unittest
from pathlib import Path


API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from logging_profiles import (  # noqa: E402
    EngineJsonFormatter,
    normalize_log_mode,
    payload_visible_in_mode,
)
from request_context import clear_request_context, set_request_id  # noqa: E402


class EngineJsonFormatterTests(unittest.TestCase):
    """Validate JSON log formatting and mode-tag behavior."""

    def tearDown(self) -> None:
        """Clear request-local context after each test."""
        clear_request_context()

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

    def test_layer_timing_is_tagged_for_focused_and_verbose(self) -> None:
        """Ensure layer timing lines are mapped to focused and verbose modes."""
        payload = self._format_record(
            logging.INFO,
            "[recommendations] layer timing: explore=12ms(3) exploit=7ms(2)",
        )
        self.assertEqual(payload["event"], "recommendations.layer_timing")
        self.assertIn("focused", payload["modes"])
        self.assertIn("verbose", payload["modes"])
        self.assertIn("context", payload)
        self.assertEqual(payload["context"]["explore"], "12ms(3)")

    def test_warning_is_visible_in_all_modes(self) -> None:
        """Ensure warning/error events stay visible in all mode views."""
        payload = self._format_record(logging.WARNING, "[recommendations] explore pool empty")
        self.assertEqual(payload["modes"], ["focused", "verbose"])
        self.assertTrue(payload_visible_in_mode(payload, "focused"))
        self.assertTrue(payload_visible_in_mode(payload, "verbose"))

    def test_request_id_is_extracted_from_message_prefix(self) -> None:
        """Extract request id from [scope][request_id] message prefix."""
        payload = self._format_record(
            logging.INFO,
            "[similar-server][8cd3e9] start limit=48 id= host= uuid=",
        )
        self.assertEqual(payload["request_id"], "8cd3e9")

    def test_request_id_is_taken_from_request_context(self) -> None:
        """Apply request id from thread-local context for generic logs."""
        set_request_id("7f33a0")
        payload = self._format_record(logging.INFO, "[recommendations] profile=home likes=yes")
        self.assertEqual(payload["request_id"], "7f33a0")

    def test_incoming_likes_body_is_normalized(self) -> None:
        """Normalize incoming likes payload to readable structured context."""
        payload = self._format_record(
            logging.INFO,
            '[recommendations] incoming likes body={"likes":[{"uuid":"u1","host":"h1"}],"user_id":null,"mode":"home"}',
        )
        self.assertEqual(payload["event"], "recommendations.incoming_likes_body")
        self.assertEqual(payload["message"], "[recommendations] incoming likes")
        self.assertEqual(payload["context"]["likes_count"], 1)
        self.assertEqual(payload["context"]["likes"][0]["uuid"], "u1")
        self.assertEqual(payload["context"]["likes"][0]["host"], "h1")
        self.assertEqual(payload["context"]["mode"], "home")

    def test_service_lifecycle_is_tagged_for_focused_and_verbose(self) -> None:
        """Ensure service lifecycle lines are visible in both logging modes."""
        payload = self._format_record(
            logging.INFO,
            "[service] lifecycle state=start component=engine run_id=abc pid=123 host=127.0.0.1 port=7171",
        )
        self.assertEqual(payload["event"], "service.lifecycle")
        self.assertNotIn("message", payload)
        self.assertIn("focused", payload["modes"])
        self.assertIn("verbose", payload["modes"])
        self.assertEqual(payload["context"]["state"], "start")

    def test_mode_normalization_falls_back_to_verbose(self) -> None:
        """Normalize unsupported mode values to verbose."""
        self.assertEqual(normalize_log_mode("focused"), "focused")
        self.assertEqual(normalize_log_mode(""), "verbose")
        self.assertEqual(normalize_log_mode("unknown"), "verbose")


if __name__ == "__main__":
    unittest.main()
