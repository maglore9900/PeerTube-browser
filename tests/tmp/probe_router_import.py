import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
API_DIR = ROOT / "engine" / "server" / "api"

CHILD = r'''
import contextlib, sqlite3, types
import server
from handlers import similar
import router
calls = []
fake = types.SimpleNamespace(_statement_deadline=contextlib.nullcontext, _respond_interrupted=lambda: calls.append("503"))
similar.SimilarHandler._serve(fake, lambda h: calls.append(h is fake))
def interrupted(h):
    raise sqlite3.OperationalError("interrupted")
similar.SimilarHandler._serve(fake, interrupted)
try:
    similar.SimilarHandler._serve(fake, lambda h: (_ for _ in ()).throw(sqlite3.OperationalError("disk I/O error")))
except sqlite3.OperationalError as exc:
    calls.append("reraised:" + str(exc))
sent = []
router.respond_json = lambda h, status, body: sent.append((status, body))
router.handle_internal_events_ingest = lambda h, s: sent.append("ingest")
router._events_ingest(object(), types.SimpleNamespace(engine_ingest_mode=None))
router._events_ingest(object(), types.SimpleNamespace(engine_ingest_mode="bridge"))
router._events_ingest(object(), types.SimpleNamespace())
print(calls, sent, hasattr(similar.SimilarHandler, "_serve_get"), hasattr(similar.SimilarHandler, "_serve_post"))
'''


def test_probe():
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    print(run.stdout, run.stderr[-2000:])
    assert run.returncode == 0
