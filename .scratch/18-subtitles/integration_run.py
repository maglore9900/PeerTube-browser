"""Plan 49 integration check: enqueue one real video, run translate-worker.py on the 3070 until the job ends, sample VRAM.

Usage (repo root): engine/.pixi/envs/default/bin/python .scratch/18-subtitles/integration_run.py <id> <host>
Writes the real engine/server/db/subtitles.db; the worker is stopped with SIGTERM once the job has ended.
"""
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / "engine/.pixi/envs/default/bin/python"
WORKER = ROOT / "engine/server/db/jobs/translate-worker.py"
SUBS = ROOT / "engine/server/db/subtitles.db"
LOG = ROOT / ".scratch/18-subtitles/worker-integration.log"
GPU = "GPU-205ff644-786e-e2b5-7aab-73e7d754f6a8"
DEADLINE_SECONDS = 900

video_id, host = sys.argv[1], sys.argv[2]

enq = subprocess.run([str(PY), str(WORKER), "enqueue", "--id", video_id, "--host", host], capture_output=True, text=True, cwd=ROOT)
print(f"enqueue exit {enq.returncode}: {enq.stdout.strip()} {enq.stderr.strip()}")
if enq.returncode not in (0,):
    sys.exit(1)


def gpu_used(pid: int) -> int:
    out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        p, mem = (x.strip() for x in line.split(","))
        if p == str(pid):
            return int(mem)
    return 0


def total_used() -> int:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout
    return int(out.split()[0])


def row() -> sqlite3.Row | None:
    conn = sqlite3.connect(f"file:{SUBS}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "select state, source, detected_language, error, cues_json, started_at, finished_at from subtitles where video_id = ? and instance_domain = ? and target_language = 'en'",
            (video_id, host),
        ).fetchone()
    finally:
        conn.close()


baseline = total_used()
env = dict(os.environ, CUDA_VISIBLE_DEVICES=GPU, PYTHONUNBUFFERED="1")
proc = subprocess.Popen([str(PY), str(WORKER), "run", "--log", str(LOG)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
t0 = time.monotonic()
peak_own = peak_total = 0
first_cues = None
last_print = 0.0
state = None
try:
    while time.monotonic() - t0 < DEADLINE_SECONDS:
        if proc.poll() is not None:
            print(f"worker exited early with {proc.returncode}")
            break
        peak_own = max(peak_own, gpu_used(proc.pid))
        peak_total = max(peak_total, total_used())
        r = row()
        state = r["state"] if r else None
        cues = len(json.loads(r["cues_json"])) if r and r["cues_json"] else 0
        if cues and first_cues is None:
            first_cues = time.monotonic() - t0
        if time.monotonic() - last_print > 10:
            print(f"{time.monotonic() - t0:6.1f}s state={state} cues={cues} vram_own={peak_own} MiB")
            last_print = time.monotonic()
        if state in ("ready", "failed", "already_english"):
            break
        time.sleep(0.5)
finally:
    elapsed = time.monotonic() - t0
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(60)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

r = row()
cues = json.loads(r["cues_json"]) if r and r["cues_json"] else []
print(f"\nend state={r['state'] if r else None} source={r['source'] if r else None} detected={r['detected_language'] if r else None} error={r['error'] if r else None}")
print(f"cues={len(cues)} first cues stored after {first_cues if first_cues is None else round(first_cues, 1)} s, job ended after {elapsed:.1f} s (worker start included)")
for cue in cues[:3] + cues[-2:]:
    print(f"  [{cue['start']:8.3f} -> {cue['end']:8.3f}] {cue['text']}")
print(f"VRAM: baseline {baseline} MiB, peak total {peak_total} MiB, worker pid peak {peak_own} MiB (limit 3072); worker exit {proc.returncode}")
