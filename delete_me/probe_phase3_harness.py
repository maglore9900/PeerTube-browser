from __future__ import annotations

import importlib.util
import logging
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"
for _p in (ROOT / "engine" / "server", ROOT / "engine" / "server" / "api"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load():
    spec = importlib.util.spec_from_file_location("updater_probe3", JOBS_DIR / "updater-worker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    updater = _load()
    jobs = tmp_path / "repo" / "engine" / "server" / "db" / "jobs"
    jobs.mkdir(parents=True)
    for name in ("merge-staging-db.py", "build-video-embeddings.py", "recompute-popularity.py", "precompute-similar-ann.py", "build-ann-index.py", "fetch-trending.py"):
        (jobs / name).write_bytes(b"")
    (jobs / "merge_rules.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(updater, "script_dir", jobs)
    crawler = tmp_path / "crawler"
    (crawler / "dist").mkdir(parents=True)
    shutil.copy(ROOT / "engine" / "crawler" / "schema.sql", crawler / "schema.sql")
    for name in ("instances-cli.js", "channels-cli.js", "videos-cli.js", "channels-videos-count-cli.js"):
        (crawler / "dist" / name).write_bytes(b"")
    prod = tmp_path / "prod.db"
    conn = sqlite3.connect(prod.as_posix())
    conn.executescript((crawler / "schema.sql").read_text(encoding="utf-8"))
    conn.execute("INSERT INTO instances(host) VALUES ('stale.example')")
    conn.commit()
    conn.close()
    join = tmp_path / "join.json"
    join.write_text("[]", encoding="utf-8")
    events = []

    def fake_run(cmd, **kwargs):
        events.append(("child", list(cmd)))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(updater, "run_similarity_stage", lambda **kw: events.append(("similarity", sorted(kw))))
    monkeypatch.setattr(sys, "argv", ["updater-worker.py", "--service-name", "peertube-engine", "--systemctl-bin", "/usr/bin/systemctl", "--systemctl-use-sudo", "--sync-join-whitelist", "--yes", "--whitelist-url", join.as_uri(), "--cpu", "--python-bin", "/opt/py", "--crawler-dir", crawler.as_posix(), "--prod-db", prod.as_posix(), "--staging-db", (tmp_path / "staging.db").as_posix(), "--similarity-db", (tmp_path / "similarity-cache.db").as_posix(), "--index-path", (tmp_path / "ann.faiss").as_posix(), "--index-meta-path", (tmp_path / "ann.faiss.json").as_posix(), "--lock-file", (tmp_path / "run.lock").as_posix(), "--logs", (tmp_path / "updater.log").as_posix()])
    error = None
    try:
        updater.main()
    except BaseException as exc:
        error = exc
    print("ERROR", repr(error))
    print("TMP", tmp_path, prod.resolve() == prod)
    for event in events:
        print("EVENT", event)
    print("COMPLETED", [r.getMessage() for r in caplog.records if "worker completed" in r.getMessage()])
    print("ROOT HANDLERS", logging.getLogger().handlers)
    print("server_config", sys.modules.get("server_config"))
    assert False
