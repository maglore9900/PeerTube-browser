"""The frontend's data modules, run in node against the real Client and Engine: a key the server
refuses surfaces as `ProfileKeyRejectedError`.

- With a stored key the server does not accept, both fetches throw `ProfileKeyRejectedError`.

`window`, `localStorage` and `sessionStorage` are the browser platform node lacks; the runner
supplies minimal in-memory ones, as `test_frontend_profile.py` does.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
QUERY = "music"
PAGE = "8"

RUNNER = """
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
globalThis.window = { location: { origin: process.env.BASE }, localStorage: globalThis.localStorage };
const m = await import(process.env.BUNDLE);
const base = process.env.BASE;
const say = (obj) => process.stdout.write(JSON.stringify(obj) + "\\n");
const channels = (rows) => rows.map((r) => [r.instance_domain, r.channel_id]);
const attempt = async (fn) => {
  try { return { ok: channels((await fn()).rows) }; }
  catch (e) { return { rejected: e instanceof m.ProfileKeyRejectedError, error: String(e) }; }
};
const upnext = () => m.fetchSimilarVideosPayload({ id: process.env.SEED_UUID, host: process.env.SEED_HOST,
  limit: process.env.PAGE, apiBase: base });
const search = () => m.fetchSearchResults({ q: process.env.QUERY, apiBase: base });
for (const step of process.argv.slice(2)) {
  const [name, arg1, arg2] = step.split("|");
  if (name === "create") say({ key: await m.createProfile(base) });
  if (name === "store") { m.storeProfileKey(arg1); say({ stored: true }); }
  if (name === "upnext") say(await attempt(upnext));
  if (name === "search") say(await attempt(search));
  if (name === "block") say({ block: await m.blockVideoSource(base, "channel", arg1, arg2) });
}
process.exit(0);
"""


def _bundle(tmp_path: Path, base: str) -> Path:
    entry = tmp_path / "entry.ts"
    entry.write_text(
        f'export * from "{FRONTEND}/src/data/profile.ts";\n'
        f'export * from "{FRONTEND}/src/data/blocks.ts";\n'
        f'export {{ fetchSimilarVideosPayload }} from "{FRONTEND}/src/data/videos.ts";\n'
        f'export {{ fetchSearchResults }} from "{FRONTEND}/src/data/search.ts";\n'
    )
    subprocess.run(
        [str(ESBUILD), str(entry), "--bundle", "--format=esm", "--platform=node",
         f"--outfile={tmp_path / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(base)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    runner = tmp_path / "runner.mjs"
    runner.write_text(RUNNER)
    return runner


def _run(runner: Path, base: str, seed: dict, steps: list[str]) -> list[dict]:
    proc = subprocess.run(
        ["node", str(runner), *steps], capture_output=True, text=True, timeout=300,
        env={"BASE": base, "BUNDLE": str(runner.parent / "bundle.mjs"), "PATH": os.environ.get("PATH", ""),
             "SEED_UUID": seed["video_uuid"], "SEED_HOST": seed["instance_domain"],
             "PAGE": PAGE, "QUERY": QUERY},
    )
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()]


def _keyless(client, method: str, path: str) -> list[dict]:
    status, body = client.request(method, path, body={} if method == "POST" else None)
    assert status == 200, body
    return body["rows"]


def _seed_and_targets(client) -> tuple[dict, dict, dict]:
    """A seed, a row from its up-next page, and a search row on neither that row's channel nor on the page."""
    search = _keyless(client, "GET", f"/api/v1/search/videos?q={QUERY}")
    seed = search[0]
    upnext = _keyless(client, "POST",
                      f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={PAGE}")
    upnext_channels = {(r["instance_domain"], r["channel_id"]) for r in upnext}
    from_search = next(r for r in search if (r["instance_domain"], r["channel_id"]) not in upnext_channels)
    return seed, upnext[0], from_search


def test_a_key_the_server_refuses_surfaces_as_profile_key_rejected_on_upnext_and_search(
        engine_client, tmp_path):
    runner = _bundle(tmp_path, engine_client.base)
    seed, _in_upnext, _in_search = _seed_and_targets(engine_client)
    unknown_key = secrets.token_urlsafe(32)  # well-formed, never issued

    accepted = _run(runner, engine_client.base, seed, ["create", "upnext", "search"])
    assert "ok" in accepted[1] and "ok" in accepted[2]  # control: a key the server knows is fine

    refused = _run(runner, engine_client.base, seed, [f"store|{unknown_key}", "upnext", "search"])
    assert refused[1].get("rejected") is True, refused[1]
    assert refused[2].get("rejected") is True, refused[2]
