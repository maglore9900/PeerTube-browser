"""Retired from `tests/active/test_translate_worker.py` in the harvest of build 56 (split translate worker timings).

- `test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job` was merged (COMBINE) with build 56's phase 1 checkpoint into `test_serve_waits_the_given_back_off_before_its_next_lookup_of_the_same_head_job`. The merged test keeps its `injected lock` / `missing file` parametrisation, crosses it with back-offs of 0.5 s and 1.0 s, and adds the upper bound `gap < backoff + GAP_SLACK_SECONDS` and a clean-return `errors == []`.
- `test_serve_refreshes_progress_every_slice_of_the_back_off_and_a_stop_during_it_returns_within_a_slice_without_another_claim` was replaced (REPLACES) by `test_serve_refreshes_progress_every_given_slice_of_the_back_off_and_a_stop_during_it_returns_within_half_a_second_without_another_claim`, which keeps every assertion, reads them at two slices (0.05 s, 0.2 s), and adds the lower bound `max(ages) > slice / 2` and `errors == []`.
- `test_run_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on` was replaced (REPLACES) by `test_run_given_stall_seconds_4_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on`, the same assertions driven through the real `run --stall-seconds 4` instead of the `-c` `STALL_DRIVER`, which is retired with it along with the constants only these tests used (`SLICE_SECONDS`, `SAMPLE_SECONDS`, `FRESH_SECONDS`, and `GAP_BACKOFF_SECONDS` 1.0, `LIVE_BACKOFF_SECONDS` 1.5, `TEST_STALL_SECONDS` 4.0 as they stood).

Kept readable; the names they use come from the active module and are not imported here, and the whole module is skipped.
"""
# ruff: noqa: F821
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="retired test, kept for reference")

# Serve back-off: serve's poll_seconds, so a stop or a progress refresh is due every slice.
SLICE_SECONDS = 0.05
# serve's backoff_seconds for the gap test; without a back-off serve was probed reclaiming about 0.1 ms after each requeue.
GAP_BACKOFF_SECONDS = 1.0
# serve's backoff_seconds for the liveness test, long enough that sampling plus the stop bound fit inside the second back-off.
LIVE_BACKOFF_SECONDS = 1.5
# Ten of the longer back-off and still under the 30 s default, so a serve waiting the default rather than the given back-off misses it.
LOOKUP_WAIT_SECONDS = 10 * LIVE_BACKOFF_SECONDS
SAMPLE_SECONDS = 0.25
# Two slices: a once-per-slice refresh was probed peaking at 0.050 s; one refreshing every other slice or less would exceed it.
FRESH_SECONDS = 2 * SLICE_SECONDS
# Loads the worker as a module, lowers its STALL_SECONDS to argv[2] and runs its main() on the rest of argv, so a stall shows within the test instead of after 600 s; every function it runs is the script's own.
STALL_DRIVER = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("translate_worker", sys.argv[1])
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
worker.STALL_SECONDS = float(sys.argv[2])
sys.argv = [sys.argv[1], *sys.argv[3:]]
worker.main()
"""
# Twice the idle loop's 2 s poll, so an idle worker never trips it, and under one 5 s tick, so at most one beat follows the claim.
TEST_STALL_SECONDS = 4.0


@pytest.mark.parametrize("injected", [True, False], ids=["injected lock", "missing file"])
def test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job(rig, monkeypatch, injected):
    """`serve`, run in-process on a daemon thread, after a whitelist.db requeue looks up the same head job again no sooner than the given back-off later, every lookup is for v-1 and never for d-1 queued behind it, and after a stop the row is queued with attempts 0 and queued_at kept."""
    lookups = _recording(rig.worker.resolve_video, locked_calls=None if injected else 0)
    monkeypatch.setattr(rig.worker, "resolve_video", lookups)
    if not injected:
        rig.whitelist.unlink()
    assert tuple(enqueue_translate_job(rig.conn, "v-1", HOST, "en", 50, QUEUED_AT)) == ("queued", "queued")
    # Queued behind v-1, so a requeue that lost v-1's place at the head would show as a d-1 lookup.
    assert tuple(enqueue_translate_job(rig.conn, "d-1", DENIED_HOST, "en", 50, QUEUED_AT + 1)) == ("queued", "queued")
    args = Namespace(whitelist_db=rig.whitelist, max_duration=MAX_DURATION, max_bytes=len(rig.clip), max_chunk_seconds=1)
    stop = threading.Event()
    thread = threading.Thread(target=rig.worker.serve, args=(rig.conn, args, StubRunner(rig), stop, {"at": time.monotonic()}), kwargs={"poll_seconds": SLICE_SECONDS, "backoff_seconds": GAP_BACKOFF_SECONDS}, daemon=True)
    thread.start()
    try:
        assert _until(lambda: len(lookups.calls) >= 2, LOOKUP_WAIT_SECONDS), lookups.calls  # control: serve reclaimed within the wait
        assert lookups.calls[1][0] - lookups.calls[0][0] >= GAP_BACKOFF_SECONDS, lookups.calls  # no sooner than the back-off after the first
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive()  # control: serve returned, so the row below is at rest
    assert {call[1:] for call in lookups.calls} == {("v-1", HOST)}, lookups.calls  # every lookup was the head job, never d-1
    row = rig.row()
    assert (row["state"], row["attempts"], row["queued_at"]) == ("queued", 0, QUEUED_AT), row  # the same head job, requeued unspent at its place


def test_serve_refreshes_progress_every_slice_of_the_back_off_and_a_stop_during_it_returns_within_a_slice_without_another_claim(rig, monkeypatch):
    """Inside `serve`'s second back-off on a deleted whitelist.db, `progress["at"]` read every 0.01 s for five slices is never more than two slices old, so the heartbeat never reads the wait as a stall; a stop set with more than 0.5 s of the back-off left ends `serve` within 0.5 s, with no lookup after the stop and the row queued with attempts 0."""
    lookups = _recording(rig.worker.resolve_video)
    monkeypatch.setattr(rig.worker, "resolve_video", lookups)
    rig.whitelist.unlink()
    assert tuple(enqueue_translate_job(rig.conn, "v-1", HOST, "en", 50, QUEUED_AT)) == ("queued", "queued")
    args = Namespace(whitelist_db=rig.whitelist, max_duration=MAX_DURATION, max_bytes=len(rig.clip), max_chunk_seconds=1)
    stop = threading.Event()
    progress = {"at": time.monotonic()}
    thread = threading.Thread(target=rig.worker.serve, args=(rig.conn, args, StubRunner(rig), stop, progress), kwargs={"poll_seconds": SLICE_SECONDS, "backoff_seconds": LIVE_BACKOFF_SECONDS}, daemon=True)
    thread.start()
    try:
        assert _until(lambda: len(lookups.calls) >= 2, LOOKUP_WAIT_SECONDS), lookups.calls  # control: serve reached its second lookup
        assert _until(lambda: rig.row().get("state") == "queued", LIVE_BACKOFF_SECONDS / 2), rig.row()  # control: the second requeue landed, so serve is in the back-off

        ages = []
        end = time.monotonic() + SAMPLE_SECONDS
        while time.monotonic() < end:
            ages.append(time.monotonic() - progress["at"])
            time.sleep(SAMPLE_EVERY_SECONDS)

        assert max(ages) < FRESH_SECONDS, ages  # no read through five slices of the wait found progress older than two slices
        assert len(lookups.calls) == 2, lookups.calls  # control: every read fell in the second back-off, not a fresh claim

        stop_at = time.monotonic()
        left = lookups.calls[1][0] + LIVE_BACKOFF_SECONDS - stop_at
        assert left > STOP_WITHIN_SECONDS, left  # control: a wait ignoring the stop would outlast the bound below
        stop.set()
        thread.join(5)
        elapsed = time.monotonic() - stop_at
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive() and elapsed < STOP_WITHIN_SECONDS, (thread.is_alive(), elapsed)  # serve returned within about one slice of the stop
    assert len(lookups.calls) == 2, lookups.calls  # no claim after the stop
    row = rig.row()
    assert (row["state"], row["attempts"]) == ("queued", 0), row  # the job is left requeued unspent


def test_run_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on(tmp_path: Path) -> None:
    """A `run` with STALL_SECONDS lowered to 4 s beats while idle; while its main loop is held in a claimed job's whitelist lookup the row's `beat_at` stays put over two due ticks; once the lookup returns, the job fails `not in whitelist` and beating resumes with the subprocess's pid."""
    _require_tools()
    paths = _paths(tmp_path)
    _whitelist(paths["whitelist"], [], deny=False)
    argv = [str(ENGINE_PY), "-c", STALL_DRIVER, str(WORKER), str(TEST_STALL_SECONDS), *_run_argv(paths)[2:]]
    out_path = tmp_path / "run.out"
    with out_path.open("wb") as out:
        proc = subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, cwd=tmp_path)
        try:
            first = _next_beat(paths["subtitles"], proc, None, FIRST_BEAT_SECONDS)
            idle = _next_beat(paths["subtitles"], proc, first, BEAT_WINDOW_SECONDS) if first is not None else None
            assert idle is not None and idle[1] == proc.pid, (first, idle, proc.poll(), out_path.read_text(encoding="utf-8", errors="replace"))  # the worker beats while idle under the lowered threshold, so the silence below is a stop

            holder = sqlite3.connect(paths["whitelist"], isolation_level=None)
            try:
                holder.execute("BEGIN EXCLUSIVE")
                conn = connect_subtitles_db(paths["subtitles"])
                try:
                    assert enqueue_translate_job(conn, *STALL_KEY, "en", 50, _now_ms()) == ("queued", "queued")  # control: one job on the queue
                finally:
                    conn.close()
                deadline = time.monotonic() + 10.0
                while _jobs(paths["subtitles"]) != [("running", None)] and time.monotonic() < deadline:
                    time.sleep(0.1)
                assert _jobs(paths["subtitles"]) == [("running", None)]  # control: the main loop claimed the job and is now in its whitelist lookup
                time.sleep(TEST_STALL_SECONDS + 1.0)
                stalled = _beat(paths["subtitles"])
                time.sleep(STALLED_WINDOW_SECONDS)
                assert proc.poll() is None, (proc.returncode, out_path.read_text(encoding="utf-8", errors="replace"))  # control: the worker is alive, so the silence below is not an exit
                assert _jobs(paths["subtitles"]) == [("running", None)]  # control: the main loop is still held, so it stalled for the whole window
                assert _beat(paths["subtitles"]) == stalled, stalled  # no beat over two due ticks while the worker's own main loop is stalled
                released_ms = _now_ms()
            finally:
                holder.close()

            resumed = _next_beat(paths["subtitles"], proc, stalled, RESUME_SECONDS)
            assert resumed is not None, (stalled, proc.poll(), _jobs(paths["subtitles"]), out_path.read_text(encoding="utf-8", errors="replace"))  # beating resumes once the main loop moves on
            assert resumed[1] == proc.pid, (resumed, proc.pid)  # the running worker's own beat
            assert resumed[0] >= released_ms, (resumed, released_ms)  # written after the main loop was let go
            assert _jobs(paths["subtitles"]) == [("failed", "not in whitelist")]  # control: the main loop finished the job it was held in

            proc.send_signal(signal.SIGTERM)
            try:
                code = proc.wait(timeout=STOP_WINDOW_SECONDS)
            except subprocess.TimeoutExpired:
                pytest.fail(f"run still alive {STOP_WINDOW_SECONDS} s after SIGTERM")
            assert code == 0, (code, out_path.read_text(encoding="utf-8", errors="replace"))  # control: a clean stop, so nothing above ran in a dying worker
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
