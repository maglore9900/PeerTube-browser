from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
import test_frontend_video_page as base  # noqa: E402

RUNNER = base.RUNNER.replace(
    """globalThis.fetch = async (input) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requested.push(url.pathname);""",
    """const log = [];
globalThis.IntersectionObserver = class { constructor(cb) { log.push({ observer: true }); } observe() {} unobserve() {} disconnect() {} };
globalThis.fetch = async (input, init) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requested.push(url.pathname);
  log.push({ method: init?.method ?? "GET", path: url.pathname, search: url.search, body: init?.body ?? null });
  if (url.pathname === "/recommendations") return new Response(JSON.stringify({ rows: Array.from({ length: 48 }, (_, i) => ({ video_id: `v${i}`, instance_domain: "videos.example" })), seed: { mode: "upnext" } }), { status: 200 });""",
).replace("process.stdout.write(JSON.stringify({ requested,", "process.stdout.write(JSON.stringify({ log, similar: byId.get(\"similar-videos\")?.innerHTML ?? null, requested,")


def test_probe(tmp_path_factory):
    out = base.bundle.__wrapped__(tmp_path_factory) if hasattr(base.bundle, "__wrapped__") else None
    out = tmp_path_factory.mktemp("probe")
    subprocess.run(
        [str(base.ESBUILD), str(base.FRONTEND / "src" / "pages" / "video-page" / "index.ts"), "--bundle", "--format=esm", "--platform=node",
         "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(base.BASE)}", "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    (out / "runner.mjs").write_text(RUNNER)
    proc = subprocess.run(["node", str(out / "runner.mjs")], capture_output=True, text=True, timeout=60,
                          env={"BASE": base.BASE, "BUNDLE": str(out / "bundle.mjs"), "PATH": os.environ.get("PATH", ""),
                               "VIDEO_BODY": json.dumps({"videoUuid": "uuid-1", "title": "t"}), "INITIALLY_HIDDEN": "[]"})
    print("RC", proc.returncode, proc.stderr[-2000:])
    page = json.loads(proc.stdout.splitlines()[-1])
    for entry in page["log"]:
        if entry.get("path") in ("/recommendations", "/api/video") or entry.get("observer"):
            print("REQ", entry)
    print("CARDS", page["similar"].count('class="similar-card-item"'))
    print("HEAD", page["similar"][:600])
    print("PATHS", sorted(set(e.get("path") for e in page["log"] if e.get("path"))), len(page["log"]))
    assert False
