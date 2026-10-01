import logging
import time
from datetime import datetime, timezone


def _plan_format_ts(created):
    stamp = datetime.fromtimestamp(created, tz=timezone.utc)
    return f"{stamp.strftime('%Y-%m-%dT%H:%M:%S')}.{stamp.microsecond // 1000:03d}Z"


def _truncating(created):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(created)) + f".{int(created % 1 * 1000):03d}Z"


def _via_msecs(record):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z"


def test_probe():
    out = {}
    for created in (1741091696.789, 1741091696.9999996):
        record = logging.LogRecord("probe", logging.INFO, "probe", 1, "m", None, None)
        record.created = created
        out[repr(created)] = {"plan": _plan_format_ts(created), "truncating": _truncating(created), "via_msecs": _via_msecs(record), "repr": f"{created:.10f}"}
    assert False, out
