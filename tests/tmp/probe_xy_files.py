import json
import sys
from urllib.request import urlopen

v = json.load(urlopen(f"https://{sys.argv[1]}/api/v1/videos/{sys.argv[2]}", timeout=10))
fs = list(v.get("files") or [])
for p in v.get("streamingPlaylists") or []:
    fs += p.get("files") or []
for f in sorted(fs, key=lambda f: f.get("size") or 0):
    print(f.get("size"), (f.get("resolution") or {}).get("label"), "hasAudio=", f.get("hasAudio"), "hasVideo=", f.get("hasVideo"), f.get("fileUrl"))
