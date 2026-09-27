import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOBS = ROOT / "engine" / "server" / "db" / "jobs"
CHANNELS = [("7", "a.example", "Alphachan"), ("7", "b.example", "Betachan"), ("8", "a.example", ""), ("9", "a.example", None)]
VIDEOS = [("v1", "a.example", "7", "Betachan"), ("v2", "b.example", "7", "Alphachan"), ("v3", "b.example", "7", "Betachan"), ("v4", "a.example", "8", "Stalename"), ("v5", "a.example", "9", "Stalename"), ("v6", "a.example", "404", "Orphanname"), ("v7", "a.example", "7", None)]
MATCH_SQL = "SELECT v.video_id FROM videos_fts JOIN videos v ON v.rowid = videos_fts.rowid WHERE videos_fts MATCH ?"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, JOBS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed(conn):
    conn.executemany("INSERT INTO channels (channel_id, instance_domain, display_name) VALUES (?, ?, ?)", CHANNELS)
    conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, channel_name, title, description, last_checked_at) VALUES (?, ?, ?, ?, 'clip ' || ?1, 'plain text', 1)", VIDEOS)


def _report(conn, label):
    for name in ("Alphachan", "Betachan"):
        print(label, name, sorted(r[0] for r in conn.execute(MATCH_SQL, (f'channel_name : "{name}"',))))
    print(label, "counts", conn.execute("SELECT COUNT(*) FROM videos_fts").fetchone()[0], conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0], "docsize", conn.execute("SELECT COUNT(*) FROM videos_fts_docsize").fetchone()[0])
    try:
        conn.execute("INSERT INTO videos_fts (videos_fts, rank) VALUES ('integrity-check', 1)")
        print(label, "integrity ok")
    except sqlite3.DatabaseError as exc:
        print(label, "integrity", exc)


def _simulated_phase3(sync, conn):
    sync.drop_videos_fts_triggers(conn)
    conn.execute("UPDATE videos SET channel_name = (SELECT c.display_name FROM channels c WHERE c.channel_id = videos.channel_id AND c.instance_domain = videos.instance_domain) WHERE EXISTS (SELECT 1 FROM channels c WHERE c.channel_id = videos.channel_id AND c.instance_domain = videos.instance_domain AND c.display_name IS NOT NULL AND c.display_name <> '' AND videos.channel_name IS NOT c.display_name)")
    sync.create_videos_fts_triggers(conn)
    sync.rebuild_videos_fts(conn)
    conn.commit()


def test_probe(tmp_path):
    sync = _load("probe3_sync", "sync-whitelist.py")
    repair = _load("probe3_repair", "repair-video-channel-names.py")
    for variant in ("unindexed", "drifted"):
        for impl in ("phase2", "phase3sim"):
            db = tmp_path / f"{variant}-{impl}.db"
            conn = sqlite3.connect(db)
            sync.ensure_content_schema(conn)
            if variant == "unindexed":
                sync.drop_videos_fts_triggers(conn)
            _seed(conn)
            conn.commit()
            if variant == "drifted":
                # v1's name corrected behind the index's back, as a run that crashed before its rebuild would leave it.
                sync.drop_videos_fts_triggers(conn)
                conn.execute("UPDATE videos SET channel_name = 'Alphachan' WHERE video_id = 'v1'")
                conn.commit()
            sync.create_videos_fts_triggers(conn)
            _report(conn, f"{variant}/{impl}/before")
            try:
                if impl == "phase2":
                    print(variant, impl, "changed", repair.repair_channel_names(conn))
                else:
                    _simulated_phase3(sync, conn)
            except sqlite3.DatabaseError as exc:
                print(variant, impl, "raised", exc)
            conn.close()
            conn = sqlite3.connect(db)
            _report(conn, f"{variant}/{impl}/after")
            conn.close()
    assert False, "probe"
