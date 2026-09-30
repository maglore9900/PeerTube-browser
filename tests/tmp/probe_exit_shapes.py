import subprocess
import sys


def test_probe_exit_shapes():
    cases = {
        "sys_exit_msg": "import sys; sys.exit('RANDOM_CACHE_REFRESH_INTERVAL_MINUTES must be a non-negative integer, got abc')",
        "raise_value_error": "raise ValueError('RANDOM_CACHE_REFRESH_INTERVAL_MINUTES must be a non-negative integer')",
        "int_fraction": "int('7.5')",
        "repr_shapes": "print(repr(None)); print(repr(0)); print(repr(7)); print(repr((60, 0)))",
    }
    for name, code in cases.items():
        run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        print(name, run.returncode, repr(run.stdout), repr(run.stderr.strip().splitlines()[-1:] if run.stderr else ""))
    assert False
