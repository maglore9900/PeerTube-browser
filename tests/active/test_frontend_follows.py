"""`follows.ts`, bundled with `profile.ts` and run in node against the real Client and Engine (`engine_client`).

- `followVideoSource` for a search row's channel and its account, and `followChannel` for another row's channel key, each resolve with the stored follow keyed as whitelist.db keys it. `listFollows` returns exactly those three. `unfollow` of the channel resolves, and `listFollows` then returns the other two.
- With a never-issued key, and with no key, `listFollows`, `followVideoSource`, `followChannel` and `unfollow` each reject with `Profile key required`.

`window` and `localStorage` are the browser platform node lacks; the runner supplies minimal in-memory ones.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
from pathlib import Path

import pytest

from conftest import identity_of

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"

FOLLOWS_RUNNER = r"""
const memory = () => { const s = new Map(); return { getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)), removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
globalThis.window = { location: { origin: process.env.BASE }, localStorage: globalThis.localStorage };
const m = await import(process.env.BUNDLE);
const base = process.env.BASE;
const say = (obj) => process.stdout.write(JSON.stringify(obj) + "\n");
const attempt = async (fn) => { try { const value = await fn(); return { ok: value ?? null }; } catch (e) { return { error: String(e?.message ?? e) }; } };
for (const [name, ...args] of JSON.parse(process.env.STEPS)) {
  if (name === "create") say({ key: await m.createProfile(base) });
  if (name === "store") { m.storeProfileKey(args[0]); say({ stored: true }); }
  if (name === "list") say(await attempt(() => m.listFollows(base)));
  if (name === "followVideo") say(await attempt(() => m.followVideoSource(base, ...args)));
  if (name === "followChannel") say(await attempt(() => m.followChannel(base, ...args)));
  if (name === "unfollow") say(await attempt(() => m.unfollow(base, args[0])));
}
process.exit(0);
"""


def _esbuild(entry: Path, out: Path, base: str = BASE, check: bool = True) -> bool:
    run = subprocess.run(
        [str(ESBUILD), str(entry), "--bundle", "--format=esm", "--platform=node", "--loader:.css=empty", f"--outfile={out}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(base)}", "--define:import.meta.env.DEV=false"],
        capture_output=True, text=True,
    )
    assert run.returncode == 0 or not check, run.stderr[-2000:]
    return run.returncode == 0


def _node(runner: Path, env: dict[str, str]) -> str:
    proc = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=120, env={"PATH": os.environ.get("PATH", ""), **env})
    assert proc.returncode == 0, proc.stderr[-4000:]
    return proc.stdout


def _key_fields(body: dict | None) -> dict:
    return {k: (body or {}).get(k) for k in ("kind", "instance_domain", "channel_id", "account_url")}


@pytest.fixture
def follows_runner(engine_client, tmp_path) -> Path:
    (tmp_path / "entry.ts").write_text(f'export * from "{FRONTEND}/src/data/profile.ts";\nexport * from "{FRONTEND}/src/data/follows.ts";\n')
    _esbuild(tmp_path / "entry.ts", tmp_path / "bundle.mjs", engine_client.base)
    (tmp_path / "runner.mjs").write_text(FOLLOWS_RUNNER)
    return tmp_path


def _follows(runner_dir: Path, base: str, steps: list[list]) -> list[dict]:
    out = _node(runner_dir / "runner.mjs", {"BASE": base, "BUNDLE": str(runner_dir / "bundle.mjs"), "STEPS": json.dumps(steps)})
    return [json.loads(line) for line in out.splitlines()]


def _keyset(follows: list[dict]) -> set[tuple]:
    return {tuple(_key_fields(f).values()) for f in follows}


def test_follows_ts_follows_a_video_s_channel_and_account_and_a_named_channel_lists_them_and_unfollows_one_through_the_real_client(engine_client, dataset, follows_runner):
    status, body = engine_client.request("GET", "/api/v1/search/videos?q=music")
    assert status == 200 and body["rows"], body
    video = body["rows"][0]
    mine = identity_of(dataset, video["video_id"], video["instance_domain"])
    # A second search row on another channel and another account, followed by its channel key alone.
    other = next(r for r in body["rows"] if (r["instance_domain"], r["channel_id"]) != (video["instance_domain"], mine["channel_id"]) and r["account_url"] != mine["account_url"])
    theirs = identity_of(dataset, other["video_id"], other["instance_domain"])
    channel_key = {"kind": "channel", "instance_domain": video["instance_domain"], "channel_id": mine["channel_id"], "account_url": ""}
    account_key = {"kind": "account", "instance_domain": "", "channel_id": "", "account_url": mine["account_url"]}
    named_key = {"kind": "channel", "instance_domain": other["instance_domain"], "channel_id": theirs["channel_id"], "account_url": ""}

    _key, by_channel, by_account, named, listed, unfollowed, relisted = _follows(follows_runner, engine_client.base, [
        ["create"], ["followVideo", "channel", video["video_uuid"], video["instance_domain"]], ["followVideo", "account", video["video_uuid"], video["instance_domain"]],
        ["followChannel", other["instance_domain"], theirs["channel_id"]], ["list"], ["unfollow", channel_key], ["list"],
    ])

    # Each add resolves with the stored follow, keyed as whitelist.db keys the video's channel, its account and the named channel.
    assert _key_fields(by_channel.get("ok")) == channel_key, by_channel  # C2
    assert _key_fields(by_account.get("ok")) == account_key, by_account  # C2
    assert _key_fields(named.get("ok")) == named_key, named  # C2
    assert "ok" in listed and _keyset(listed["ok"]) == {tuple(k.values()) for k in (channel_key, account_key, named_key)}, listed  # C2
    assert unfollowed == {"ok": None}, unfollowed  # C2
    # Only the channel followed through the video is gone; an unfollow that sends the wrong key leaves three, one that matches loosely takes the named channel too.
    assert "ok" in relisted and _keyset(relisted["ok"]) == {tuple(k.values()) for k in (account_key, named_key)}, relisted  # C2


@pytest.mark.parametrize("stored", [secrets.token_urlsafe(32), None], ids=["unknown-key", "no-key"])
def test_every_follows_ts_call_the_client_answers_401_rejects_with_profile_key_required(engine_client, follows_runner, stored):
    key_step = [["store", stored]] if stored else []
    target = {"kind": "channel", "instance_domain": "tube.example", "channel_id": "1", "account_url": ""}
    out = _follows(follows_runner, engine_client.base, [*key_step, ["list"], ["followVideo", "channel", "uuid-x", "tube.example"], ["followChannel", "tube.example", "1"], ["unfollow", target]])
    results = out[len(key_step):]

    # The Client answers each of these 401 {"error": "Profile key required"} (observed); a module that swallows it resolves, and one that replaces the message reads otherwise.
    assert results == [{"error": "Profile key required"}] * 4, results  # C2
