"""Throwaway probe: what translate-worker.py enqueue prints and exits with for the phase 2 requests, and what recovery answers."""
import importlib.util
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("cp2", HERE / "test_49_translate_whisper_worker_phase2.py")
cp2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp2)


def test_probe(tmp_path):
    paths = {"whitelist": tmp_path / "whitelist.db", "subtitles": tmp_path / "subtitles.db"}
    cp2._whitelist(paths["whitelist"])
    cp2._subtitles(paths["subtitles"]).close()
    for args in (["--id", "u-1", "--host", "PEER.Example."], ["--id", "u-1", "--host", "peer.example"], ["--id", "no-such-video", "--host", "peer.example"], ["--id", "du-1", "--host", "denied.example"], ["--id", "lu-1", "--host", "peer.example", "--max-duration", "600"], ["--id", "mu-1", "--host", "peer.example", "--max-duration", "600"], ["--id", "u-1", "--host", ""], ["--id", "u-2", "--host", "peer.example", "--cap", "1"]):
        print(args, cp2._enqueue(paths, args))
    print(cp2._rows(paths["subtitles"]))
    from data.subtitles import claim_translate_job, recover_translate_jobs
    conn = cp2._subtitles(paths["subtitles"])
    print(dict(claim_translate_job(conn, "en", 5000)), recover_translate_jobs(conn, 9000))
    conn.close()
    assert False
