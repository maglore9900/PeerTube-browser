import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_53_source_instance_fetch_adapter_phase3 as checkpoint  # noqa: E402
from test_53_source_instance_fetch_adapter_phase3 import *  # noqa: E402,F401,F403

MODE = "bounded"

DRAFT = r'''
import json as _json, logging as _logging
from urllib.request import Request as _Request
from data import source_fetch as _sf
from handlers import video as _video
_MODE = "%s"
def _draft(host, path):
    try:
        if _MODE == "follows":
            with _sf.build_opener().open(_Request(f"https://{host}{path}", headers={"accept": "application/json"}), timeout=4.0) as resp:
                raw = resp.read()
        else:
            raw = _sf.fetch_bounded(host, path, headers={"accept": "application/json"}, max_bytes=10**9 if _MODE == "uncapped" else _sf.FETCH_MAX_BYTES)
        data = _json.loads(raw.decode("utf-8"))
    except (_sf.SourceFetchFailed, ValueError, OSError) as exc:
        _logging.info("draft failed %%s", exc)
        return None
    return data if isinstance(data, dict) else None
_video.fetch_instance_json = _draft
''' % MODE

exec(DRAFT)
checkpoint.HTTP_CHILD = checkpoint.HTTP_CHILD.replace("from handlers.similar import SimilarHandler\n", "from handlers.similar import SimilarHandler\n" + DRAFT, 1)
