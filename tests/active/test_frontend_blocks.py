"""The frontend's data modules, run in node against the real Client and Engine: a channel blocked
through `blocks.ts` leaves the rows they fetch, and a key the server refuses surfaces as
`ProfileKeyRejectedError`.

- After `blockVideoSource` for a video's channel, the rows `fetchSimilarVideosPayload` (up
  next) and `fetchSearchResults` return omit that channel, where the same calls before the
  block included it: both fetches send the stored key, and search does not serve a cached
  pre-block page.
- With a stored key the server does not accept, both fetches throw `ProfileKeyRejectedError`.

The up-next fetch is pinned with `exclude` (the runner's `EXCLUDE`) to a fixed set of the seed's
pool (conftest `pin_upnext`), so it is served whole, not drawn.

`window`, `localStorage` and `sessionStorage` are the browser platform node lacks; the runner
supplies minimal in-memory ones, as `test_frontend_profile.py` does.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
from pathlib import Path

from conftest import pin_upnext, upnext_pool

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
  limit: process.env.PAGE, apiBase: base }, JSON.parse(process.env.EXCLUDE));
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


def _run(runner: Path, base: str, seed: dict, steps: list[str], exclude: list[dict[str, str]] | None = None) -> list[dict]:
    proc = subprocess.run(
        ["node", str(runner), *steps], capture_output=True, text=True, timeout=300,
        env={"BASE": base, "BUNDLE": str(runner.parent / "bundle.mjs"), "PATH": os.environ.get("PATH", ""),
             "SEED_UUID": seed["video_uuid"], "SEED_HOST": seed["instance_domain"],
             "PAGE": PAGE, "QUERY": QUERY, "EXCLUDE": json.dumps(exclude or [])},
    )
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()]


def _channel(row: dict) -> list[str]:
    """A row's channel as the runner prints it."""
    return [row["instance_domain"], row["channel_id"]]


def _search(client) -> list[dict]:
    status, body = client.request("GET", f"/api/v1/search/videos?q={QUERY}")
    assert status == 200, body
    return body["rows"]


def _seed_and_targets(client, engine) -> tuple[dict, list[dict], list[dict[str, str]], dict]:
    """A seed, its `/recommendations` pool's first page of rows, the `exclude` pinning its up-next page to exactly those rows, and a search row on none of their channels."""
    search = _search(client)
    seed = search[0]
    pinned = upnext_pool(engine, "/recommendations", seed)[:int(PAGE)]
    exclude = pin_upnext(engine, "/recommendations", seed, pinned)
    from_search = next(r for r in search if _channel(r) not in [_channel(p) for p in pinned])
    return seed, pinned, exclude, from_search


def test_a_channel_blocked_through_the_module_leaves_the_upnext_and_search_rows_it_fetches(
        engine_client, engine, tmp_path):
    runner = _bundle(tmp_path, engine_client.base)
    seed, pinned, exclude, in_search = _seed_and_targets(engine_client, engine)
    in_upnext = pinned[0]
    pinned_channels = [_channel(r) for r in pinned]

    out = _run(runner, engine_client.base, seed, [
        "create", "upnext", "search",
        f"block|{in_upnext['video_uuid']}|{in_upnext['instance_domain']}",
        f"block|{in_search['video_uuid']}|{in_search['instance_domain']}",
        "upnext", "search",
    ], exclude)
    _key, before_upnext, before_search, _b1, _b2, after_upnext, after_search = out

    # Control: pinned, the up-next fetch before the block is the pinned rows whole, the target's channel among them.
    assert sorted(before_upnext["ok"]) == sorted(pinned_channels), before_upnext
    assert _channel(in_search) in before_search["ok"], before_search
    assert after_upnext["ok"] and after_search["ok"]  # the pages still have rows
    assert sorted(after_upnext["ok"]) == sorted(c for c in pinned_channels if c != _channel(in_upnext)), after_upnext
    assert _channel(in_search) not in after_search["ok"], after_search


def test_a_key_the_server_refuses_surfaces_as_profile_key_rejected_on_upnext_and_search(
        engine_client, tmp_path):
    runner = _bundle(tmp_path, engine_client.base)
    seed = _search(engine_client)[0]
    unknown_key = secrets.token_urlsafe(32)  # well-formed, never issued

    accepted = _run(runner, engine_client.base, seed, ["create", "upnext", "search"])
    assert "ok" in accepted[1] and "ok" in accepted[2]  # control: a key the server knows is fine

    refused = _run(runner, engine_client.base, seed, [f"store|{unknown_key}", "upnext", "search"])
    assert refused[1].get("rejected") is True, refused[1]
    assert refused[2].get("rejected") is True, refused[2]
