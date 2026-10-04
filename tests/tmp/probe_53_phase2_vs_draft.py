"""Probe: the phase 2 checkpoint's tests run against the plan's drafted route and worker edits; MUTATION (set on this module) picks a wrong variant."""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "active"))

import test_53_source_instance_fetch_adapter_phase2 as checkpoint  # noqa: E402
from data import source_fetch  # noqa: E402
import handlers.internal_translate as route  # noqa: E402

MUTATION = None


def _fetch(host, path, budget_at):
    try:
        if MUTATION == "fresh budget":
            return source_fetch.fetch_bounded(host, path)
        return source_fetch.fetch_bounded(host, path, budget_at=budget_at)
    except source_fetch.SourceFetchFailed as exc:
        if MUTATION == "no reason logged":
            logging.info("[translate] instance fetch failed host=%s path=%s", host, path)
        else:
            logging.info("[translate] instance fetch failed host=%s path=%s: %s", host, path, exc)
        return None


def fetch_instance_track(host, video_key):
    budget_at = time.monotonic() + route.REQUEST_BUDGET_SECONDS
    listing = _fetch(host, f"/api/v1/videos/{quote(video_key, safe='')}/captions", budget_at)
    path = route.pick_english_track_path(listing, host) if listing is not None else None
    raw = _fetch(host, path, budget_at) if path is not None else None
    if raw is None:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    cues = route.parse_webvtt(text)
    return (text, cues) if cues is not None else None


route.fetch_instance_track = fetch_instance_track
route.same_host_https = source_fetch.same_host_https

ORIGINAL_WORKER = checkpoint.WORKER
FEED = '''    def _feed(self) -> None:
        """draft"""
        try:
            stream_media(self.url, self.host, self.max_bytes, self.proc.stdin.write, self.stop)
        except BrokenPipeError:
            pass
        except SourceFetchFailed as exc:
            self._fail(str(exc))
        finally:
            try:
                self.proc.stdin.close()
            except OSError:
                pass

'''


def draft_worker(mutation):
    """The worker script with the plan's draft edits (and the mutation's) applied, written beside this probe."""
    source = ORIGINAL_WORKER.read_text()
    source = source.replace("from handlers.internal_translate import FETCH_DEADLINE_SECONDS, READ_CHUNK_BYTES, SOURCE_INSTANCE, TARGET_LANGUAGE, SameHostRedirectHandler, fetch_bounded, fetch_instance_track", "from data.source_fetch import READ_CHUNK_BYTES, SourceFetchFailed, fetch_bounded, stream_media\nfrom handlers.internal_translate import SOURCE_INSTANCE, TARGET_LANGUAGE, fetch_instance_track")
    source, count = re.subn(r"    def _feed\(self\) -> None:.*?(?=    def _read\(self\))", lambda m: FEED, source, flags=re.S)
    assert count == 1
    reason = '"video JSON fetch failed"' if mutation == "bare" else 'f"video JSON fetch failed: {exc}"'
    nonobject = 'f"video JSON fetch failed: {exc}"' if mutation == "reason on a non-object" else '"video JSON fetch failed"'
    video_json = f'''    try:
        raw = fetch_bounded(instance, f"/api/v1/videos/{{quote(video_key, safe='')}}")
    except SourceFetchFailed as exc:
        raise JobFailed({reason}) from exc
    try:
        video = json.loads(raw.decode("utf-8"))
        exc = "not an object"
    except (ValueError, RecursionError) as error:
        video = None
        exc = error
    if not isinstance(video, dict):
        raise JobFailed({nonobject})
'''
    source, count = re.subn(r"    raw = fetch_bounded\(instance, .*?raise JobFailed\(\"video JSON fetch failed\"\)\n", lambda m: video_json, source, flags=re.S)
    assert count == 1
    path = HERE / f"probe_53_draft_translate_worker_{(mutation or 'none').replace(' ', '_')}.py"
    path.write_text(source)
    return path


checkpoint.WORKER = draft_worker(None)

from test_53_source_instance_fetch_adapter_phase2 import *  # noqa: E402,F401,F403
