"""Throwaway probe: runs the phase 1 test functions against a draft-shaped fetch_metadata_by_uuids and four wrong variants."""
from __future__ import annotations

import pytest

import test_14_batch_like_resolution_phase1 as t
from test_14_batch_like_resolution_phase1 import conn  # noqa: F401
from data import metadata

SELECT = "SELECT v.video_id, v.video_uuid, v.video_numeric_id, v.instance_domain, v.channel_id, v.channel_name, v.channel_url, c.display_name AS channel_display_name, c.avatar_url AS channel_avatar_url, v.account_name, v.account_url, v.title, v.description, v.tags_json, v.category, v.published_at, v.video_url, v.duration, v.thumbnail_url, v.embed_path, v.views, v.likes, v.dislikes, v.comments_count, v.nsfw, v.preview_path, v.last_checked_at, e.embedding_dim, e.model_name FROM video_embeddings e JOIN videos v ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain LEFT JOIN channels c ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain WHERE "


def make(pick="lowest", nocase=False, filter_after=False):
    def fetch(conn, entries, error_threshold=None):
        pairs = {}
        for entry in entries:
            pairs.setdefault(f"{entry['video_uuid']}::{entry['instance_domain']}", (entry["video_uuid"], entry["instance_domain"]))
        if not pairs:
            return {}
        result = {}
        for batch in metadata._chunk(list(pairs.values()), 450):
            coll = " COLLATE NOCASE" if nocase else ""
            where = f"(v.video_uuid{coll}, v.instance_domain{coll}) IN ({', '.join(['(?, ?)'] * len(batch))})"
            params = [value for pair in batch for value in pair]
            if error_threshold and not filter_after:
                where += " AND (v.error_count IS NULL OR v.error_count < ?)"
                params.append(error_threshold)
            rows = [dict(row) for row in conn.execute(SELECT + where, params)]
            for row in rows:
                key = f"{row['video_uuid']}::{row['instance_domain']}"
                if pick == "first" and key in result:
                    continue
                if pick == "lowest" and key in result and row["video_id"] >= result[key]["video_id"]:
                    continue
                result[key] = row
            if filter_after and error_threshold:
                for key, row in list(result.items()):
                    count = conn.execute("SELECT error_count FROM videos WHERE video_id = ? AND instance_domain = ?", (row["video_id"], row["instance_domain"])).fetchone()[0]
                    if count is not None and count >= error_threshold:
                        del result[key]
        return result
    return fetch


TESTS = [name for name in dir(t) if name.startswith("test_")]


@pytest.mark.parametrize("name", TESTS)
def test_correct(name, conn, monkeypatch):
    monkeypatch.setattr(metadata, "fetch_metadata_by_uuids", make(), raising=False)
    getattr(t, name)(conn)


@pytest.mark.parametrize("variant", ["first", "last", "nocase", "filter_after"])
def test_wrong(variant, conn, monkeypatch):
    impl = {"first": make(pick="first"), "last": make(pick="last"), "nocase": make(nocase=True), "filter_after": make(filter_after=True)}[variant]
    monkeypatch.setattr(metadata, "fetch_metadata_by_uuids", impl, raising=False)
    failed = []
    for name in TESTS:
        try:
            getattr(t, name)(conn)
        except AssertionError:
            failed.append(name)
        conn.execute("UPDATE videos SET error_count = 0 WHERE video_id = 's1'")
        conn.execute("DELETE FROM videos WHERE instance_domain = 'bulk.example'")
        conn.execute("DELETE FROM video_embeddings WHERE instance_domain = 'bulk.example'")
    print(variant, "fails", failed)
    assert failed
