"""Apply one named harvest mutation by exact string replacement, refusing unless its anchor occurs exactly once."""
import sys
from pathlib import Path

WORKER = "engine/server/db/jobs/translate-worker.py"
SUBTITLES = "engine/server/data/subtitles.py"
HANDLER = "engine/server/api/handlers/internal_translate.py"
SERVER = "client/backend/server.py"
PAGE = "client/frontend/src/pages/video-page/translate.ts"

MUTATIONS = {
    "M1": (WORKER, '        raise JobFailed("video JSON fetch failed")\n    url = pick_media_url(video)', '        raise JobFailed("video JSON fetch failed")\n    if not isinstance(video.get("duration"), int) or video["duration"] > 600:\n        raise JobFailed("video duration unknown")\n    url = pick_media_url(video)'),
    "M2": (WORKER, "data = self.proc.stdout.read1(min(READ_CHUNK_BYTES, room))", "data = self.proc.stdout.read1(READ_CHUNK_BYTES)"),
    "M3": (WORKER, "return lease is not None and lease <= expired_at and job.abandon(expired_at)", "return lease is not None and lease > expired_at and job.abandon(expired_at)"),
    "M4": (WORKER, "    expired_at = now_ms() - TRANSLATE_LEASE_MS\n    try:\n        lease = job.read_lease()", "    expired_at = now_ms() + TRANSLATE_LEASE_MS\n    try:\n        lease = job.read_lease()"),
    "M5": (SUBTITLES, "DELETE FROM subtitles WHERE state = 'queued' AND target_language = ? AND wanted_at IS NOT NULL AND wanted_at <= ?", "DELETE FROM subtitles WHERE state = 'queued' AND target_language = ? AND wanted_at IS NOT NULL AND wanted_at < ?"),
    "M6": (HANDLER, 'if stored is not None and stored[0] in ("queued", "running"):', 'if stored is not None and stored[0] in ("queued",):'),
    "M7": (SUBTITLES, "SET wanted_at = MIN(wanted_at, ?)", "SET wanted_at = MAX(wanted_at, ?)"),
    "M8": (HANDLER, "                cancel_translate_lease(conn, canonical_id, instance, TARGET_LANGUAGE, now_ms() - TRANSLATE_LEASE_MS + TRANSLATE_CANCEL_GRACE_MS)\n                stored, available = fetch_subtitle_state(conn, canonical_id, instance, TARGET_LANGUAGE), _generation_available(conn)", "                stored = fetch_subtitle_state(conn, canonical_id, instance, TARGET_LANGUAGE)\n                enqueue_translate_job(conn, canonical_id, instance, TARGET_LANGUAGE, SUBTITLE_QUEUE_CAP, now_ms()) if stored is None else cancel_translate_lease(conn, canonical_id, instance, TARGET_LANGUAGE, now_ms() - TRANSLATE_LEASE_MS + TRANSLATE_CANCEL_GRACE_MS)\n                available = _generation_available(conn)"),
    "M9": (HANDLER, "                cancel_translate_lease(conn, canonical_id, instance, TARGET_LANGUAGE, now_ms() - TRANSLATE_LEASE_MS + TRANSLATE_CANCEL_GRACE_MS)", "                _generation_available(conn) and cancel_translate_lease(conn, canonical_id, instance, TARGET_LANGUAGE, now_ms() - TRANSLATE_LEASE_MS + TRANSLATE_CANCEL_GRACE_MS)"),
    "M10": (SERVER, "self._handle_translate_post(cancel_translate)", "self._handle_translate_post(request_translate)"),
    "M11": (PAGE, "void requestsSettled.then(() => cancelTranslate(apiBase, video.id, video.host))", "void Promise.resolve().then(() => cancelTranslate(apiBase, video.id, video.host))"),
    "M12": (PAGE, "void requestsSettled.then(() => cancelTranslate(apiBase, video.id, video.host))", "void requestsSettled.then(() => new Promise((resolve) => setTimeout(resolve, 500))).then(() => cancelTranslate(apiBase, video.id, video.host))"),
    "M13": (PAGE, "(ticket === requestTicket ? applyFetched(state, apiBase, video, ticket) : undefined)", "(ticket === requestTicket ? applyState(state, apiBase, video, ticket) : undefined)"),
}

if sys.argv[1] == "--check":
    for key, (path, old, _) in MUTATIONS.items():
        print(key, path, Path(path).read_text().count(old))
    sys.exit(0)
name = sys.argv[1]
path, old, new = MUTATIONS[name]
text = Path(path).read_text()
count = text.count(old)
if count != 1:
    sys.exit(f"{name}: anchor occurs {count} times in {path}, refusing")
Path(path).write_text(text.replace(old, new))
print(f"{name}: mutated {path}")
