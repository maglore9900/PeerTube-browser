import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_11_fast_similars_response_phase1 import CHANNEL, CHANNEL_PATH, DETAIL, DETAIL_PATH, HOST, UUID, _get, sync_job  # noqa: E402,F401


def test_probe(sync_job, tmp_path):
    omitting = {DETAIL_PATH: {"description": "Live description B", "views": 900, "channel": {"name": "live_slug", "displayName": "Live Chan B", "followersCount": 60}}}
    by_video_id = {DETAIL_PATH: DETAIL, "/api/v1/videos/v1": DETAIL, CHANNEL_PATH: CHANNEL}
    reports = _get(sync_job, tmp_path, (f"/api/video?id={UUID}&host={HOST}", omitting), (f"/api/video?id=v1&host={HOST}", by_video_id))
    for report in reports:
        print(json.dumps(report, sort_keys=True))
