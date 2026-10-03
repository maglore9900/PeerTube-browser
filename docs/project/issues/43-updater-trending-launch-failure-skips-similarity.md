# A trending stage that fails to launch skips the similarity stage

Status: bug, needs-triage
Origin: build 45-trending-from-source-instances (plan `docs/project/plans/46-45-trending-from-source-instances.md`), Step 9

## Problem

The requirements for the updater's trending stage say: "A failure of the stage itself (the job exits non-zero or raises) … is logged. The similarity stage still runs, and the run exits non-zero at the end."

`engine/server/db/jobs/updater-worker.py` `main()` wraps the trending `run_cmd` in `except subprocess.CalledProcessError` only. `run_cmd` calls `subprocess.run(cmd, cwd=cwd, check=True)`, so only a child that started and exited non-zero is caught. A child that cannot be started raises an `OSError` from `subprocess.run` (for example `FileNotFoundError` or `PermissionError` on `args.python_bin`, or a failed fork under memory or process limits). That exception is not caught: the run fails at once, and `run_similarity_stage` never runs.

The plan's draft had `except Exception`; the delivered code narrowed it. The tests in `tests/active/test_updater_worker.py` only fake a `CalledProcessError`, so nothing covers this case.

How likely it is: low. `fetch-trending.py` is in the required-files check, so a missing script fails the run before anything starts, and `args.python_bin` has already launched earlier stages in the same run. What remains is an interpreter removed or made unexecutable mid-run, or a fork failing. When it happens, the weekly similarity rebuild is lost for that run.

## Proposed solution

Catch `OSError` alongside `subprocess.CalledProcessError` around the trending `run_cmd`. Log it, hold it, run similarity, then raise `RuntimeError("trending stage failed")` from it, as is done for a non-zero exit. A gating test fakes `subprocess.run` raising `OSError` for the trending argv only, and asserts that similarity still runs once and that the run then raises.

Do not widen to `Exception`: a programming error in the updater itself should still fail fast.

## Related

- `docs/project/issues/archive/38-hot-trending-by-growth.md` and ADR-0010: the trending stage.
- `engine/server/db/jobs/docs/UPDATER_WORKER.md`: the stage's failure rule, which describes only a non-zero exit.

## Comments
