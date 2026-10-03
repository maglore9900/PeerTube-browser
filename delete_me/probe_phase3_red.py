"""Probe copy of the phase 3 checkpoint, run against the unchanged worker to see each test's red."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("phase3_checkpoint_copy", Path(__file__).with_name("test_45_trending_from_source_instances_phase3.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
globals().update({name: value for name, value in vars(_mod).items() if not name.startswith("__")})
