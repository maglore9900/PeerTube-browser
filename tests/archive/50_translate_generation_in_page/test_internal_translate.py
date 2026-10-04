"""Retired from `tests/active/test_internal_translate.py` in the harvest of build 50-translate-generation-in-page.

`test_an_engine_start_creates_the_subtitles_table_at_its_configured_path_and_routes_internal_translate_behind_the_bridge_gate` was merged (COMBINE) with that build's phase 2 checkpoint test of the enqueue route's bridge gate. Its every assertion lives on in `test_an_engine_start_creates_the_subtitles_table_at_its_configured_path_and_routes_internal_translate_and_its_enqueue_behind_the_bridge_gate`, which also asserts `/internal/translate/enqueue` answers 404 `Video not found` with the bridge token and 401 without it, from the same single Engine start. Kept readable; the names it uses come from the active module and are not imported here, and the whole module is skipped.

The retired module docstring line read:

Startup: server.py run with `DEFAULT_SUBTITLES_DB_PATH` overridden to a missing file answers health, has created that file with a `subtitles` table, answers `/internal/translate` with the token for an unknown video `404 Video not found` (an Engine without the route answers `404 Not found`), and without the token 401.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="retired test, kept for reference")


def test_an_engine_start_creates_the_subtitles_table_at_its_configured_path_and_routes_internal_translate_behind_the_bridge_gate(tmp_path):
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"  # noqa: F821
    subtitles_path = tmp_path / "subtitles.db"
    assert not subtitles_path.exists()  # control: only the start can create it
    env = {**os.environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": BRIDGE_TOKEN}  # noqa: F821
    log_path = tmp_path / "engine.log"
    port = _free_port()  # noqa: F821
    base = f"http://127.0.0.1:{port}"
    with open(log_path, "w") as log:
        with open(ENGINE_START_LOCK, "w") as start_lock:  # noqa: F821
            fcntl.flock(start_lock, fcntl.LOCK_EX)  # noqa: F821
            proc = subprocess.Popen([str(ENGINE_PY), "-c", VARIANT_RUNNER, str(ENGINE_SERVER), json.dumps({"DEFAULT_SUBTITLES_DB_PATH": str(subtitles_path)}), "--host", "127.0.0.1", "--port", str(port), "--no-random-cache-refresh"], env=env, stdout=log, stderr=log)  # noqa: F821
            healthy = False
            deadline = time.time() + HEALTHY_WITHIN_SECONDS  # noqa: F821
            while proc.poll() is None and time.time() < deadline and not healthy:  # noqa: F821
                try:
                    with urllib.request.urlopen(base + "/api/health", timeout=5) as resp:  # noqa: F821
                        healthy = resp.status == 200
                except OSError:
                    time.sleep(0.1)  # noqa: F821
    try:
        assert healthy, f"the variant Engine did not answer /api/health 200 within {HEALTHY_WITHIN_SECONDS}s (exit {proc.poll()}); see {log_path}"  # noqa: F821
        assert subtitles_path.exists(), f"the Engine start did not create {subtitles_path}"
        conn = sqlite3.connect(f"file:{subtitles_path}?mode=ro", uri=True)  # noqa: F821
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            conn.close()
        assert "subtitles" in tables, tables
        # An Engine without the route falls through to 404 {"error": "Not found"}; this video and host resolve to no row, so the handler answers before any fetch.
        assert _post(base, "/internal/translate", {"id": "no-such-video", "host": "no-such-host.invalid"}, {"X-Bridge-Token": BRIDGE_TOKEN}) == (404, {"error": "Video not found"})  # noqa: F821
        assert _post(base, "/internal/translate", {"id": "no-such-video", "host": "no-such-host.invalid"}, {}) == (401, {"error": "Unauthorized"})  # behind the bridge gate  # noqa: F821
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=STOP_WITHIN_SECONDS)  # noqa: F821
        except subprocess.TimeoutExpired:  # noqa: F821
            proc.kill()
            proc.wait()
