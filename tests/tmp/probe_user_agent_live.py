"""Live probe: the adapter's real fetch against the two hosts that 403'd Python-urllib."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine/server"))
from data.source_fetch import fetch_bounded  # noqa: E402


def test_makertube_and_toby3d_answer_the_adapter():
    for host, video in (("makertube.net", "897a658e-c857-48a2-9781-e22b9b27c672"), ("video.toby3d.me", "d8f61a3b-4490-4d6b-baef-8713aa2647ba")):
        assert fetch_bounded(host, f"/api/v1/videos/{video}", max_bytes=2_000_000).startswith(b"{")
