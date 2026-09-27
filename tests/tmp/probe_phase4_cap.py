import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_14_batch_like_resolution_phase4 import LIKES, VIDEOS, _client_backend, _engine, client_server, load_liked_keys, resolve_profile  # noqa: E402
from urllib.parse import urlparse  # noqa: E402


def test_probe(tmp_path):
    with _engine(VIDEOS) as (engine_base, received), _client_backend(tmp_path, engine_base) as client:
        status, body = client.request("POST", "/api/user-profile/likes", body={"likes": LIKES})
    print("LIKESPAGE", [(p, len(b["entries"]), b["entries"][0], b["entries"][-1]) for p, b in received], status, len(body["likes"]), body["likes"][0]["video_id"], body["likes"][-1]["video_id"])
    assert False


def test_probe_import(tmp_path):
    with _engine(VIDEOS) as (engine_base, received), _client_backend(tmp_path, engine_base) as client:
        status, minted = client.request("POST", "/api/profile")
        status, body = client.request("POST", "/api/profile/likes/import", headers={"X-Profile-Key": minted["key"]}, body={"likes": LIKES})
        conn = client_server.connect_db(client.db_path)
        liked = load_liked_keys(conn, resolve_profile(conn, minted["key"]))
        conn.close()
    print("IMPORT", [(p, len(b["entries"]), b["entries"][0], b["entries"][-1]) for p, b in received], status, body, len(liked), sorted(liked)[0], sorted(liked)[-1])
    assert False


def test_probe_recs(tmp_path):
    with _engine(VIDEOS) as (engine_base, received), _client_backend(tmp_path, engine_base) as client:
        status, _ = client.request("POST", "/recommendations", body={"likes": LIKES})
    print("RECS", status, [(p, urlparse(p).path, len(b["likes"]), b["likes"][0], b["likes"][-1]) for p, b in received])
    assert False
