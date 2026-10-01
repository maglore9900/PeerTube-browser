import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_probe(monkeypatch):
    spec = importlib.util.spec_from_file_location("updater_worker_probe", ROOT / "engine/server/db/jobs/updater-worker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    argv = ["--mode", "prod", "--service-name", "peertube-engine", "--systemctl-bin", "/x/bin/systemctl", "--systemctl-use-sudo", "--engine-upstream-snippet", "/etc/nginx/peertube-engine-upstream.conf", "--gpu", "--skip-local-dead", "--concurrency", "5", "--timeout-ms", "15000", "--max-retries", "3"]
    monkeypatch.setattr(sys, "argv", ["updater-worker.py", *argv])
    args = module.parse_args()
    print("OBSERVED", (args.engine_upstream_snippet, args.skip_systemctl, args.systemctl_use_sudo, args.systemctl_bin))
    assert False
