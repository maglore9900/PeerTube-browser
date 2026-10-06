"""Probe: the checkpoint's helpers against hand-made indexes, today's index paths and today's handler."""
import importlib.util
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_54_follow_channels_and_accounts_phase1 as cp  # noqa: E402


def test_key_columns_reads(tmp_path):
    right = sqlite3.connect(tmp_path / "right.db")
    right.executescript(cp.CRAWL_SCHEMA.read_text(encoding="utf-8"))
    right.execute("CREATE INDEX idx_videos_channel_published ON videos (instance_domain, channel_id, published_at DESC, video_id DESC)")
    right.execute("CREATE INDEX idx_videos_account_published ON videos (account_url, published_at DESC, video_id DESC)")
    print("hand-made right == EXPECTED", cp._key_columns(right) == cp.EXPECTED_INDEXES)
    asc = sqlite3.connect(tmp_path / "asc.db")
    asc.executescript(cp.CRAWL_SCHEMA.read_text(encoding="utf-8"))
    asc.execute("CREATE INDEX idx_videos_channel_published ON videos (instance_domain, channel_id, published_at, video_id)")
    asc.execute("CREATE INDEX idx_videos_account_published ON videos (account_url, published_at DESC, video_id DESC)")
    print("asc variant", cp._key_columns(asc), cp._key_columns(asc) == cp.EXPECTED_INDEXES)
    today = sqlite3.connect(tmp_path / "today.db")
    today.executescript(cp.CRAWL_SCHEMA.read_text(encoding="utf-8"))
    cp.create_video_embeddings_table(today)
    cp.ensure_video_indexes(today)
    print("ensure_video_indexes today", cp._key_columns(today))
    spec = importlib.util.spec_from_file_location("sync_probe_54", cp.SYNC_JOB)
    job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(job)
    sync = sqlite3.connect(tmp_path / "sync.db")
    for _ in range(2):
        job.ensure_whitelist_schema(sync)
        job.ensure_content_schema(sync)
    print("sync schema twice today", cp._key_columns(sync))


def test_walk_today(tmp_path):
    db = cp._catalogue(tmp_path / "c.db", blocked=False)
    (walk,) = cp._walk([[db, cp.FOLLOWING_PATH, cp.MAIN_FOLLOWS]])
    print("served today", cp._served(walk))
    print("expected", cp._pages(cp.MAIN_PAGES))
