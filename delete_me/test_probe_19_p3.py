"""Probe: the phase-3 checkpoint body against a stand-in of the planned formatter, and against today's emit."""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

TMP = Path(__file__).resolve().parent
if str(TMP) not in sys.path:
    sys.path.insert(0, str(TMP))

import test_19_timestamped_request_logs_phase3 as checkpoint  # noqa: E402
from conftest import client_server  # noqa: E402


def _format_ts(record):
    return datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class _Formatter(logging.Formatter):
    def format(self, record):
        payload = {"ts": _format_ts(record), "level": record.levelname, "service": "client-backend", "event": getattr(record, "client_event", None) or "client.log", "message": record.getMessage()}
        context = getattr(record, "client_context", None)
        if context:
            payload["context"] = context
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _configure():
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(_Formatter(os.environ.get("LOG_FORMAT")))
    root.addHandler(handler)


def _emit(level, event, message, context=None):
    logging.log(level, message, extra={"client_event": event, "client_context": context})


def test_planned_shape_passes(monkeypatch):
    monkeypatch.setattr(client_server, "configure_client_logging", _configure, raising=False)
    monkeypatch.setattr(client_server, "_emit_client_log", _emit)
    before = logging.getLogger().handlers[:]
    checkpoint.test_client_records_leave_as_json_lines_in_client_key_order_with_utc_ts_and_bare_ones_as_client_log(monkeypatch)
    print("RESTORED", logging.getLogger().handlers == before, "TZ", os.environ.get("TZ"))


def _local_ts(record):
    return datetime.fromtimestamp(record.created).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(record.msecs):03d}Z"


@pytest.mark.parametrize("wrong", ["local_z", "msecs", "today_emit"])
def test_wrong_fails(monkeypatch, wrong):
    if wrong == "local_z":
        monkeypatch.setattr(sys.modules[__name__], "_format_ts", _local_ts)
    if wrong == "msecs":
        monkeypatch.setattr(sys.modules[__name__], "_format_ts", lambda r: datetime.fromtimestamp(int(r.created), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(r.msecs):03d}Z")
    monkeypatch.setattr(client_server, "configure_client_logging", _configure, raising=False)
    if wrong != "today_emit":
        monkeypatch.setattr(client_server, "_emit_client_log", _emit)
    with pytest.raises(AssertionError) as caught:
        checkpoint.test_client_records_leave_as_json_lines_in_client_key_order_with_utc_ts_and_bare_ones_as_client_log(monkeypatch)
    print("WRONG", wrong, str(caught.value).splitlines()[0][:300])
