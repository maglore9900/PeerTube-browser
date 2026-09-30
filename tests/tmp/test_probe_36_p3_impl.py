"""Probe: the mixer's per-request flag, and the gateway's handling of nsfw values."""
import itertools
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

from conftest import client_backend, dataset, engine, engine_client  # noqa: E402,F401

IPS = (f"198.18.200.{n + 1}" for n in itertools.count())
LIKES = [{"uuid": uuid, "host": "video02.videohost.top"} for uuid in ("f4e114a2-e70e-4a3c-af92-3efe3071abbc", "0e9ab678-8f3c-4305-97c9-ba9586536999", "4577ad2f-8462-4c78-8212-c4470a4f6db5")]


def test_probe(engine, engine_client, dataset):
    flagged = {(r["video_id"], r["instance_domain"]) for r in dataset.execute("SELECT video_id, instance_domain FROM videos WHERE nsfw = 1")}
    for suffix in ("&nsfw=1", "", "&nsfw=1", "&nsfw=true"):
        status, body = engine.request("POST", f"/recommendations?mode=recommendations&limit=96{suffix}", headers={"X-Client-IP": next(IPS)}, body={"likes": LIKES})
        keys = [(r["video_id"], r["instance_domain"]) for r in body["rows"]]
        print("MIX", repr(suffix), status, len(keys), len(set(keys) & flagged))
    for suffix in ("&nsfw=1", "", f"&nsfw={quote(' 1')}", "&nsfw=true"):
        status, body = engine_client.request("POST", f"/recommendations?mode=recent{suffix}", headers={"X-Forwarded-For": next(IPS)}, body={})
        keys = [(r["video_id"], r["instance_domain"]) for r in body.get("rows", [])] if isinstance(body, dict) else []
        print("GATEWAY", repr(suffix), status, len(keys), len(set(keys) & flagged), body if status != 200 else "")
    assert False, "probe"
