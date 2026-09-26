"""The frontend's reactions data module (`data/reactions.ts`), run in node against the real Client
and Engine.

Without a profile key:
- After a `like` the Client accepts through `sendReaction`, `fetchReaction` reads the video
  liked, while another video reads not liked; after the `undo_like` that follows, the video
  reads not liked.
- A `like` the Client refuses, for a video the Engine does not know or from a Client that
  cannot publish, makes `sendReaction` throw the Client's refusal and leaves `getStoredLikes()`
  as it was; an accepted like on the same store then does add to it. A refused `undo_like`
  leaves the like in the store.

With a profile key:
- `fetchReaction` reads back the state the profile holds after each `sendReaction` action:
  liked after `like`, disliked and not liked after `dislike` on the liked video, neither after
  `undo_dislike`, liked and not disliked after `like` on a disliked video, and neither after
  `undo_like`. At each step the Client's own reaction route agrees, and a dislike made through
  the Client directly is what `fetchReaction` reads next. A key the Client refuses makes
  `fetchReaction` throw `ProfileKeyRejectedError`.
- A `like` the profile then holds leaves the video out of every browser storage entry, where
  the same like without a key puts it in `getStoredLikes()`.

Moving local likes into a profile:
- With a key, after `importLocalLikes` the profile reads every video `localLikes:v1` held as
  liked, a video it did not hold stays unliked, and `getStoredLikes()` is empty; a second
  import, with nothing left to import, imports 0.
- When the Client refuses the import (a key it does not know), `importLocalLikes` throws
  `ProfileKeyRejectedError` and `getStoredLikes()` returns the likes it returned before.

Cards:
- `renderVideoCard` given `cardReaction(row)`, over the rows `fetchSearchResults` returns,
  renders the likes stat active for the row the Client marked liked (with a key) and for the
  row held in `localLikes:v1` (without a key), renders the dislikes stat active for the row the
  Client marked disliked, and renders no active stat on any other row. With a key, a like left
  in `localLikes:v1` marks nothing.

Tests that need a like the Client accepts use `engine_client`, which publishes into the live
whitelist.db, and withdraw every Like they published with an accepted `undo_like`; the others
use `unpublished_client`. `window`, `localStorage` and `sessionStorage` are the browser platform
node lacks; the runner supplies minimal in-memory ones, as `test_frontend_blocks.py` does.
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid as uuidlib
from pathlib import Path
from urllib.parse import urlencode

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
UNKNOWN_KEY = "A" * 43  # the shape a minted key has, issued to nobody
QUERY = "music"
SEARCH = f"/api/v1/search/videos?q={QUERY}"

RUNNER = """
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k), entries: () => [...s.entries()] }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
globalThis.window = { location: { origin: process.env.BASE }, localStorage: globalThis.localStorage };
const m = await import(process.env.BUNDLE);
const base = process.env.BASE;
const lines = process.stdin[Symbol.asyncIterator]();
const say = (obj) => process.stdout.write(JSON.stringify(obj) + "\\n");
const attempt = async (fn) => {
  try { return await fn(); }
  catch (e) { return { error: String(e && e.message), rejected: e instanceof m.ProfileKeyRejectedError }; }
};
const seed = (likes) => localStorage.setItem("localLikes:v1",
  JSON.stringify(likes.map(([u, h]) => ({ video_uuid: u, instance_domain: h }))));
for (const step of process.argv.slice(2)) {
  const [name, a, b, c] = step.split("|");
  if (name === "seed") { seed([[a, b]]); say({ seeded: 1 }); }
  if (name === "seedlist") { const likes = JSON.parse(a); seed(likes); say({ seeded: likes.length }); }
  if (name === "create") say({ key: await m.createProfile(base) });
  if (name === "store") { m.storeProfileKey(a); say({ stored_key: true }); }
  if (name === "stored") say({ stored: m.getStoredLikes().map((e) => [e.video_uuid, e.instance_domain]) });
  if (name === "browser") say({ entries: [...localStorage.entries(), ...sessionStorage.entries()]
    .filter(([k]) => k !== "profileKey:v1") });
  if (name === "read") say(await attempt(() => m.fetchReaction(base, { uuid: a, host: b })));
  if (name === "react") say(await attempt(async () => ({ ok: await m.sendReaction(base, a, { uuid: b, host: c }) })));
  if (name === "import") say(await attempt(async () => ({ imported: await m.importLocalLikes(base) })));
  if (name === "cards") {
    const rows = (await m.fetchSearchResults({ q: process.env.QUERY, apiBase: base })).rows ?? [];
    const cards = {};
    for (const row of rows) {
      try {
        const html = m.renderVideoCard(row, { reaction: m.cardReaction(row) });
        cards[m.resolveVideoKey(row)] = {
          likes: /class="stat likes active"/.test(html),
          dislikes: /class="stat dislikes active"/.test(html),
        };
      } catch (e) { cards[m.resolveVideoKey(row)] = { error: String(e && e.message) }; }
    }
    say({ cards });
  }
  if (name === "wait") await lines.next();
}
process.exit(0);
"""


def _bundle(tmp_path: Path, base: str) -> Path:
    entry = tmp_path / "entry.ts"
    entry.write_text(
        f'export {{ cardReaction, fetchReaction, importLocalLikes, sendReaction }} from "{FRONTEND}/src/data/reactions.ts";\n'
        f'export {{ getStoredLikes }} from "{FRONTEND}/src/data/local-likes.ts";\n'
        f'export {{ ProfileKeyRejectedError, createProfile, storeProfileKey }} from "{FRONTEND}/src/data/profile.ts";\n'
        f'export {{ renderVideoCard, resolveVideoKey }} from "{FRONTEND}/src/components/video-card.ts";\n'
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


def _env(runner: Path, base: str) -> dict[str, str]:
    return {"BASE": base, "BUNDLE": str(runner.parent / "bundle.mjs"), "PATH": os.environ.get("PATH", ""),
            "QUERY": QUERY}


def _run(runner: Path, base: str, steps: list[str]) -> list[dict]:
    """Run steps without pauses and return one JSON object per reporting step."""
    proc = subprocess.run(["node", str(runner), *steps], capture_output=True, text=True, timeout=300,
                          env=_env(runner, base), stdin=subprocess.DEVNULL)
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()]


class _Node:
    """One node process running the bundled modules; `wait` steps pause it until resumed."""

    def __init__(self, runner: Path, base: str, steps: list[str]) -> None:
        self.proc = subprocess.Popen(
            ["node", str(runner), *steps], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=_env(runner, base),
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
        assert self.proc.wait(timeout=60) == 0, self.proc.stderr.read()


def _runner(tmp_path: Path, name: str, base: str) -> Path:
    (tmp_path / name).mkdir()
    return _bundle(tmp_path / name, base)


def _videos(dataset, n: int) -> list[dict]:
    """n embedded, error-free videos from different channels, which the Engine resolves."""
    rows = dataset.execute(
        "SELECT v.video_uuid, v.instance_domain FROM videos v JOIN video_embeddings e "
        "ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
        "WHERE v.error_count = 0 GROUP BY v.channel_id, v.instance_domain ORDER BY v.rowid LIMIT ?",
        (n,),
    ).fetchall()
    assert len(rows) == n
    return [{"uuid": r["video_uuid"], "host": r["instance_domain"]} for r in rows]


def _server_reaction(client, key: str, video: dict) -> tuple[bool, bool]:
    status, body = client.request("GET", f"/api/profile/reaction?{urlencode(video)}",
                                  headers={"X-Profile-Key": key})
    assert status == 200, body
    return body["liked"], body["disliked"]


def _act(client, key: str | None, action: str, video: dict) -> None:
    headers = {"X-Profile-Key": key} if key else None
    status, body = client.request("POST", "/api/user-action", headers=headers, body={"action": action, **video})
    assert status == 200, body


def _withdraw_if_liked(client, key: str | None, video: dict) -> None:
    """Un-like a video the profile still likes, so no published Like is left behind."""
    if key and _server_reaction(client, key, video)[0]:
        _act(client, key, "undo_like", video)


# --- without a key ------------------------------------------------------------------------


def test_a_keyless_like_reads_back_liked_and_its_undo_reads_back_not_liked(engine_client, dataset, tmp_path):
    runner = _bundle(tmp_path, engine_client.base)
    video, other = _videos(dataset, 2)
    v, o = f"{video['uuid']}|{video['host']}", f"{other['uuid']}|{other['host']}"
    liked, undone = {}, {}
    try:
        liked, after_like, other_after, undone, after_undo = _run(
            runner, engine_client.base,
            [f"react|like|{v}", f"read|{v}", f"read|{o}", f"react|undo_like|{v}", f"read|{v}"],
        )
    finally:
        if "ok" in liked and "ok" not in undone:  # published, and the test's own undo did not withdraw it
            _act(engine_client, None, "undo_like", video)

    assert after_like.get("liked") is True, (liked, after_like)
    assert "ok" in liked, liked  # sendReaction returned rather than threw
    assert other_after.get("liked") is False, other_after  # a like of one video is not a like of every video
    assert "ok" in undone, undone
    assert after_undo.get("liked") is False, after_undo


def test_a_keyless_like_the_client_refuses_throws_and_leaves_the_stored_likes_unchanged(
        engine_client, unpublished_client, dataset, tmp_path):
    video, kept = _videos(dataset, 2)
    unknown = {"uuid": str(uuidlib.uuid4()), "host": video["host"]}  # well-formed, not in the dataset
    seed = f"seed|{kept['uuid']}|{kept['host']}"
    kept_entry = [[kept["uuid"], kept["host"]]]

    # Refused by the Engine: the video does not exist.
    runner = _runner(tmp_path, "a", engine_client.base)
    accepted = {}
    try:
        _s, before, refused, after, accepted, after_accept = _run(runner, engine_client.base, [
            seed, "stored", f"react|like|{unknown['uuid']}|{unknown['host']}", "stored",
            f"react|like|{video['uuid']}|{video['host']}", "stored",
        ])
    finally:
        if "ok" in accepted:  # only a Like that was published is withdrawn
            _act(engine_client, None, "undo_like", video)
    assert before["stored"] == kept_entry  # control: the store holds something to lose
    assert refused.get("error") == "Video not found in Engine", refused  # the Client's refusal
    assert after["stored"] == kept_entry
    assert "ok" in accepted, accepted  # control: this store does take an accepted like
    assert [video["uuid"], video["host"]] in after_accept["stored"]

    # Refused by a Client that cannot publish the Like.
    runner = _runner(tmp_path, "b", unpublished_client.base)
    _s, before, refused, after, refused_undo, after_undo = _run(runner, unpublished_client.base, [
        seed, "stored", f"react|like|{video['uuid']}|{video['host']}", "stored",
        f"react|undo_like|{kept['uuid']}|{kept['host']}", "stored",
    ])
    assert before["stored"] == kept_entry
    assert refused.get("error") == "Failed to send action", refused  # the 502
    assert after["stored"] == kept_entry
    # A refused un-like keeps the like it would have removed.
    assert refused_undo.get("error") == "Failed to send action", refused_undo
    assert after_undo["stored"] == kept_entry


# --- with a key ---------------------------------------------------------------------------


def test_with_a_key_fetch_reaction_reads_the_profile_s_state_after_each_action(
        engine_client, dataset, tmp_path):
    runner = _bundle(tmp_path, engine_client.base)
    (video,) = _videos(dataset, 1)
    v = f"{video['uuid']}|{video['host']}"
    node = _Node(runner, engine_client.base, [
        "create",
        f"react|like|{v}", f"read|{v}", "wait",
        f"react|dislike|{v}", f"read|{v}", "wait",
        f"react|undo_dislike|{v}", f"read|{v}", "wait",
        # Python dislikes the video through the Client here, outside the module.
        f"read|{v}", "wait",
        f"react|like|{v}", f"read|{v}", "wait",
        f"react|undo_like|{v}", f"read|{v}", "wait",
    ])
    key = None
    acts, reads, server = [], [], []
    try:
        key = node.read()["key"]
        for step in range(6):
            if step != 3:
                acts.append(node.read())
            reads.append(node.read())
            server.append(_server_reaction(engine_client, key, video))
            if step == 2:
                _act(engine_client, key, "dislike", video)  # out of band: not through sendReaction
            node.resume()
        node.finish()
    finally:
        _withdraw_if_liked(engine_client, key, video)

    pairs = [(r.get("liked"), r.get("disliked")) for r in reads]
    assert pairs[0] == (True, False), reads[0]  # after like
    assert pairs[1] == (False, True), reads[1]  # after dislike on the liked video
    assert pairs[2] == (False, False), reads[2]  # after undo_dislike
    assert pairs[3] == (False, True), reads[3]  # the profile's state, changed outside the module
    assert pairs[4] == (True, False), reads[4]  # after like on that disliked video
    assert pairs[5] == (False, False), reads[5]  # after undo_like
    assert server == pairs  # at every step the module read what the profile holds
    assert all("ok" in a for a in acts), acts  # every action, and so every withdrawal, was accepted

    # A key the Client refuses surfaces as ProfileKeyRejectedError, not as "not liked".
    refused_runner = _runner(tmp_path, "refused", engine_client.base)
    _stored, refused = _run(refused_runner, engine_client.base, [f"store|{UNKNOWN_KEY}", f"read|{v}"])
    assert refused.get("rejected") is True, refused


def test_with_a_key_a_like_the_profile_holds_is_not_kept_in_the_browser(engine_client, dataset, tmp_path):
    (video,) = _videos(dataset, 1)
    v = f"{video['uuid']}|{video['host']}"
    target = [video["uuid"], video["host"]]

    # Control: the same like without a key is kept in the browser.
    runner = _runner(tmp_path, "keyless", engine_client.base)
    keyless_like, keyless_stored, keyless_undo = _run(
        runner, engine_client.base, [f"react|like|{v}", "stored", f"react|undo_like|{v}"])
    assert "ok" in keyless_like and "ok" in keyless_undo, (keyless_like, keyless_undo)
    assert target in keyless_stored["stored"]

    runner = _runner(tmp_path, "keyed", engine_client.base)
    node = _Node(runner, engine_client.base,
                 ["create", f"react|like|{v}", "stored", "browser", "wait", f"react|undo_like|{v}"])
    key = None
    try:
        key = node.read()["key"]
        keyed_like, keyed_stored, browser = node.read(), node.read(), node.read()
        held = _server_reaction(engine_client, key, video)
        node.resume()
        keyed_undo = node.read()
        node.finish()
    finally:
        _withdraw_if_liked(engine_client, key, video)
    assert "ok" in keyed_like, keyed_like
    assert held == (True, False)  # the like was accepted: the profile holds it
    assert target not in keyed_stored["stored"], keyed_stored
    assert not any(video["uuid"] in value for _k, value in browser["entries"]), browser
    assert "ok" in keyed_undo, keyed_undo


# --- moving local likes into a profile ----------------------------------------------------


def _liked(client, key: str, video: list[str]) -> bool:
    return _server_reaction(client, key, {"uuid": video[0], "host": video[1]})[0]


def test_with_a_key_the_import_moves_every_local_like_into_the_profile_and_empties_the_store(
        unpublished_client, dataset, tmp_path):
    runner = _bundle(tmp_path, unpublished_client.base)
    *held, never = [[v["uuid"], v["host"]] for v in _videos(dataset, 4)]
    _seeded, created, imported, after, again = _run(runner, unpublished_client.base, [
        f"seedlist|{json.dumps(held)}", "create", "import", "stored", "import",
    ])
    key = created["key"]

    assert all(_liked(unpublished_client, key, video) for video in held), imported
    assert not _liked(unpublished_client, key, never)  # the import likes what the store held, not everything
    assert after["stored"] == [], after
    assert again == {"imported": 0}, again  # an empty store imports nothing


def test_an_import_the_client_refuses_keeps_the_local_likes(unpublished_client, dataset, tmp_path):
    runner = _bundle(tmp_path, unpublished_client.base)
    held = [[v["uuid"], v["host"]] for v in _videos(dataset, 2)]
    _seeded, _key, before, refused, after = _run(runner, unpublished_client.base, [
        f"seedlist|{json.dumps(held)}", f"store|{UNKNOWN_KEY}", "stored", "import", "stored",
    ])

    assert before["stored"] == held  # control: the store holds something to lose
    assert refused.get("rejected") is True, refused  # refused by the Client
    assert after["stored"] == held


# --- cards --------------------------------------------------------------------------------


def _search_rows(client) -> list[dict]:
    status, body = client.request("GET", SEARCH)
    assert status == 200 and body["rows"], body
    return body["rows"]


def _card_key(row: dict) -> str:
    return f"{row['instance_domain']}::{row['video_uuid']}"


def _unmarked(cards: dict, *marked: dict) -> dict:
    """The cards of every row but `marked` that render an active stat, or an error."""
    skip = {_card_key(r) for r in marked}
    return {k: c for k, c in cards.items() if k not in skip and c != {"likes": False, "dislikes": False}}


def test_a_card_shows_the_like_or_dislike_the_client_marked_or_the_like_the_browser_holds_and_nothing_else(
        unpublished_client, tmp_path):
    client = unpublished_client
    runner = _bundle(tmp_path, client.base)
    liked, disliked, neutral = _search_rows(client)[:3]
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    key = body["key"]
    # An unpublished Client stores the like, then answers 502 for the publish it cannot send;
    # a dislike of an unliked video publishes nothing and is answered 200.
    for action, row, expected in (("like", liked, 502), ("dislike", disliked, 200)):
        status, body = client.request("POST", "/api/user-action", headers={"X-Profile-Key": key},
                                      body={"action": action, "uuid": row["video_uuid"], "host": row["instance_domain"]})
        assert status == expected, (action, status, body)
    stale = f"seed|{neutral['video_uuid']}|{neutral['instance_domain']}"

    # With a key, and a like of another row left behind in the browser's store.
    (keyed,) = _run(runner, client.base, [stale, f"store|{key}", "cards"])[2:]
    assert keyed["cards"].get(_card_key(liked)) == {"likes": True, "dislikes": False}, keyed["cards"].get(_card_key(liked))
    assert keyed["cards"].get(_card_key(disliked)) == {"likes": False, "dislikes": True}  # the dislike shows too
    assert _card_key(neutral) in keyed["cards"] and _unmarked(keyed["cards"], liked, disliked) == {}

    # Without a key the like comes from the browser's own store: a different row this time.
    (local,) = _run(runner, client.base, [stale, "cards"])[1:]
    assert local["cards"].get(_card_key(neutral)) == {"likes": True, "dislikes": False}
    assert _unmarked(local["cards"], neutral) == {}  # the profile's like and dislike are not the browser's
