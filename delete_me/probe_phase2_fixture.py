"""Probe: the phase-2 handler's existing collaborators import in the test interpreter, and on the fixture whitelist.db resolve_video_row and list_active_denied_hosts answer as the checkpoint will rely on."""
import io
import json
import sqlite3
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT / "engine" / "server", ROOT / "engine" / "server" / "api"):
    sys.path.insert(0, str(_path))


class Request:
    def __init__(self, body):
        raw = json.dumps(body).encode("utf-8")
        self.headers = {"content-length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.responses = []
        self.wfile = SimpleNamespace(write=lambda data: self.responses[-1].append(json.loads(data)))

    def send_response(self, status):
        self.responses.append([status])

    def send_header(self, name, value):
        pass

    def end_headers(self):
        pass


def test_probe(tmp_path):
    seen = []
    print = lambda *args: seen.append(" ".join(str(arg) for arg in args))  # noqa: A001
    import data.db, data.moderation, data.time, handlers.video, http_utils, server_config  # noqa: F401
    print("numpy loaded:", "numpy" in sys.modules)
    print("now_ms:", data.time.now_ms())
    db = sqlite3.connect(tmp_path / "whitelist.db", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE videos (video_id TEXT, video_uuid TEXT, instance_domain TEXT, channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT, embed_path TEXT, published_at TEXT, video_url TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, tags_json TEXT, category TEXT, nsfw INTEGER, language TEXT, duration INTEGER, thumbnail_url TEXT, last_checked_at TEXT, error_count INTEGER)")
    db.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, channel_name TEXT, display_name TEXT, followers_count INTEGER, avatar_url TEXT)")
    data.moderation.ensure_moderation_schema(db)
    db.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, error_count) VALUES ('v-1', 'u-1', 'peer.example', 0)")
    db.execute("INSERT INTO instance_denylist (host, is_active, created_at, updated_at) VALUES ('DENIED.EXAMPLE', 1, 0, 0)")
    db.commit()
    server = SimpleNamespace(db=db, db_lock=threading.Lock(), video_error_threshold=3)
    print("normalize PEER.Example.:", data.moderation.normalize_host("PEER.Example."))
    resolved = handlers.video.resolve_video_row(Request({}), server, {"id": ["u-1"], "host": [data.moderation.normalize_host("PEER.Example.")]})
    print("resolve by uuid:", resolved and (resolved[0]["video_id"], resolved[0]["instance_domain"], resolved[1], resolved[2]))
    unknown = Request({})
    print("resolve unknown:", handlers.video.resolve_video_row(unknown, server, {"id": ["nope"], "host": ["peer.example"]}), unknown.responses)
    print("denied:", data.moderation.list_active_denied_hosts(db))
    body = Request({"id": " u-1 ", "host": "PEER.Example."})
    print("read_json_body:", http_utils.read_json_body(body))
    print("statement timeout default:", server_config.DEFAULT_STATEMENT_TIMEOUT_SECONDS)
    with data.db.statement_deadline(5.0):
        print("statement_deadline ran with no handler installed")
    assert False, "\n".join(seen)
