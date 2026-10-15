import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = ["a.example", "b.example", "c.example", "d.example", "e.example", "f.example", "g.example", "h.example", "i.example", "j.example", "k.example", "l.example", "Mixed.Example.", "Upper.Example", "Peer.Tube.", "Video.Host.", "Watch.Example.", "Tube.Example."]


def test_probe_groups():
    for host in CANDIDATES:
        raw = int(hashlib.sha1(host.encode("utf-8")).hexdigest(), 16) % 7
        norm_host = host.strip().lower().strip(".")
        norm = int(hashlib.sha1(norm_host.encode("utf-8")).hexdigest(), 16) % 7
        print(f"GROUP {host!r} raw={raw} normalised={norm_host!r}:{norm}")
    schema = (ROOT / "engine" / "crawler" / "schema.sql").read_text(encoding="utf-8")
    print(re.search(r"CREATE TABLE[^;]*instances[^;]*;", schema).group(0))
    assert False
