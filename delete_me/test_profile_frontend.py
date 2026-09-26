"""Checkpoint for plan 06, Phase 4 — the frontend profile data module.

must_prove:
  C1 — After `createProfile`, `resetUserProfileLikes` clears the likes of the profile the
       server issued, and without a stored key it clears no profile's likes.
  C2 — After `rotateProfileKey`, the key `getProfileKey` returns is accepted by
       `GET /api/user-profile` and the previous one is not.

The data modules run in node, bundled by the project's own esbuild. `window` and
`localStorage` are the browser platform node lacks, so the runner supplies minimal ones.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from lib.users_store import record_like

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"

RUNNER = """
const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};
globalThis.window = { location: { origin: process.env.BASE }, localStorage: globalThis.localStorage };
const m = await import(process.env.BUNDLE);
const lines = process.stdin[Symbol.asyncIterator]();
const say = (obj) => process.stdout.write(JSON.stringify(obj) + "\\n");
const wait = async () => (await lines.next()).value;
const base = process.env.BASE;
for (const step of process.argv.slice(2)) {
  if (step === "create") say({ key: await m.createProfile(base) });
  if (step === "reset") { await m.resetUserProfileLikes(base); say({ reset: true }); }
  if (step === "rotate") { const old = m.getProfileKey(); await m.rotateProfileKey(base); say({ old, now: m.getProfileKey() }); }
  if (step === "wait") { await wait(); }
}
process.exit(0);
"""


def _bundle(tmp_path: Path, base: str) -> Path:
    entry = tmp_path / "entry.ts"
    entry.write_text(
        f'export * from "{FRONTEND}/src/data/profile.ts";\n'
        f'export {{ resetUserProfileLikes }} from "{FRONTEND}/src/data/user-profile.ts";\n'
    )
    out = tmp_path / "bundle.mjs"
    subprocess.run(
        [str(ESBUILD), str(entry), "--bundle", "--format=esm", "--platform=node",
         f"--outfile={out}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(base)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    runner = tmp_path / "runner.mjs"
    runner.write_text(RUNNER)
    return runner


class _Node:
    """One node process running the bundled modules, fed a step at a time over stdin."""

    def __init__(self, runner: Path, base: str, steps: list[str]) -> None:
        self.proc = subprocess.Popen(
            ["node", str(runner), *steps], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
            env={"BASE": base, "BUNDLE": str(runner.parent / "bundle.mjs"), "PATH": _node_path()},
        )

    def read(self) -> dict:
        line = self.proc.stdout.readline()
        assert line, self.proc.stderr.read()
        return json.loads(line)

    def resume(self) -> None:
        self.proc.stdin.write("go\n")
        self.proc.stdin.flush()

    def finish(self) -> None:
        self.proc.stdin.close()
        assert self.proc.wait(timeout=30) == 0, self.proc.stderr.read()


def _node_path() -> str:
    import os
    return os.environ.get("PATH", "")


def _profile_id(client, key: str) -> str:
    status, body = client.request("GET", "/api/user-profile", headers={"X-Profile-Key": key})
    assert status == 200, body
    return body["user_id"]


def _like_count(client, key: str) -> int:
    status, body = client.request("GET", "/api/user-profile", headers={"X-Profile-Key": key})
    assert status == 200, body
    return len(body["likes"])


def _seed_like(db_path, profile_id: str, video_id: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    record_like(conn, profile_id, "like",
                {"video_id": video_id, "instance_domain": "h.example", "video_uuid": f"u-{video_id}"}, 100)
    conn.close()


def _mint(client) -> tuple[str, str]:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return body["profile_id"], body["key"]


def test_reset_clears_the_created_profile_and_without_a_key_clears_none(client_backend, tmp_path):
    runner = _bundle(tmp_path, client_backend.base)
    bystander_id, bystander_key = _mint(client_backend)
    _seed_like(client_backend.db_path, bystander_id, "vb")

    # A browser that creates a profile, then resets once its likes exist.
    node = _Node(runner, client_backend.base, ["create", "wait", "reset"])
    key = node.read()["key"]
    _seed_like(client_backend.db_path, _profile_id(client_backend, key), "v1")
    assert _like_count(client_backend, key) == 1  # control: there is something to clear
    node.resume()
    assert node.read() == {"reset": True}
    node.finish()
    assert _like_count(client_backend, key) == 0  # C1

    # A browser with no stored key: its reset reaches no profile, neither the bystander
    # nor the one just created, which gets a like back first so its loss would show.
    _seed_like(client_backend.db_path, _profile_id(client_backend, key), "v2")
    fresh = _Node(runner, client_backend.base, ["reset"])
    assert fresh.read() == {"reset": True}
    fresh.finish()
    assert _like_count(client_backend, bystander_key) == 1  # C1
    assert _like_count(client_backend, key) == 1  # C1


def test_after_rotation_the_browser_holds_the_key_the_server_accepts(client_backend, tmp_path):
    runner = _bundle(tmp_path, client_backend.base)
    node = _Node(runner, client_backend.base, ["create", "rotate"])
    created = node.read()["key"]
    rotated = node.read()
    node.finish()

    assert rotated["old"] == created
    assert rotated["now"] != created
    assert client_backend.request("GET", "/api/user-profile",
                                  headers={"X-Profile-Key": rotated["now"]})[0] == 200  # C2
    assert client_backend.request("GET", "/api/user-profile",
                                  headers={"X-Profile-Key": rotated["old"]})[0] == 401  # C2
