"""Probe: the phase-4 checkpoint's tests, re-exported, run against today's launchers to read where each goes red."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("checkpoint_phase4_copy", Path(__file__).with_name("test_63_catalog_update_weekly_increments_phase4.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
worker = _mod.worker
test_prod = _mod.test_prod_updater_unit_runs_one_increment_of_seven_daily_at_20
test_dev = _mod.test_dev_updater_unit_runs_one_increment_of_seven_daily_at_20
test_override = _mod.test_catalog_update_passes_increments_seven_ahead_of_operator_flags_so_increments_zero_overrides
test_plain = _mod.test_catalog_update_without_operator_flags_passes_increments_seven
