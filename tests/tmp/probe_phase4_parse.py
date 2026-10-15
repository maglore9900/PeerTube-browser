import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PROD = "--mode prod --service-name peertube-engine --systemctl-bin /tmp/x/bin/systemctl --systemctl-use-sudo --engine-upstream-snippet /tmp/x/nginx/peertube-engine-upstream.conf --gpu --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3".split()
DEV = "--mode dev --service-name peertube-engine-dev --systemctl-bin /tmp/x/bin/systemctl --systemctl-use-sudo --gpu --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3".split()
CATALOG = "--systemctl-bin /tmp/tmp.x/systemctl --service-name local-engine --gpu --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3".split()


def test_probe(monkeypatch):
    spec = importlib.util.spec_from_file_location("probe_worker", ROOT / "engine" / "server" / "db" / "jobs" / "updater-worker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, args in [("prod", PROD), ("prod+7", PROD + ["--increments", "7"]), ("dev+7", DEV + ["--increments", "7"]), ("cat", CATALOG), ("cat+7", CATALOG + ["--increments", "7"]), ("cat+7+0", CATALOG + ["--increments", "7", "--increments", "0"])]:
        monkeypatch.setattr(sys, "argv", ["updater-worker.py", *args])
        print(name, repr(module.parse_args().increments))
    assert False, "show output"
