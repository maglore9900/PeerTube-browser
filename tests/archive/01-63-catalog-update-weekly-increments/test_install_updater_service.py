"""Retired from `tests/active/test_install_updater_service.py` in build 01-63-catalog-update-weekly-increments (plan 01), step 7, phase 4.

Retired whole: `test_updater_installer_dev_dry_run_keeps_single_name_rule`. Why, and what answers its concern now, is in this folder's `README.md`.

The original code of the retired function follows unchanged, as an excerpt: lines 180-191 of the file as it stood. The helpers it calls (`Tree`, `_report`, `_previews`, `_exec_start`, `UPDATER_INSTALLER`) stay in the active file.
"""
# --- excerpt: lines 180-191 ---


def test_updater_installer_dev_dry_run_keeps_single_name_rule(tmp_path: Path) -> None:
    """A dev updater install `--dry-run --with-updater-timer --force`, with the snippet override set, exits 0 with today's single-name sudoers rule for `peertube-engine-dev` and today's `ExecStart` exactly, with no `--engine-upstream-snippet`."""
    tree = Tree(tmp_path)
    systemctl = tree.systemctl

    run = tree.run(UPDATER_INSTALLER, ["--mode", "dev", "--service-user", tree.user, "--with-updater-timer", "--force"])
    report = _report(tree, run)
    previews = _previews(run.stdout)

    assert run.returncode == 0, report  # control
    assert [line for line in previews.get("sudoers", []) if line.strip()] == [f"{tree.user} ALL=(root) NOPASSWD: {systemctl} stop peertube-engine-dev, {systemctl} start peertube-engine-dev"], report  # dev keeps its single-name rule
    assert _exec_start(previews.get("service", []), report) == f"/usr/bin/bash -lc 'set -euo pipefail; {tree.venv_py} {tree.real_project}/engine/server/db/jobs/updater-worker.py --mode dev --service-name peertube-engine-dev --systemctl-bin {systemctl} --systemctl-use-sudo --gpu --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3'", report  # dev unchanged, no snippet even with the override set
