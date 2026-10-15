import subprocess


def test_probe_cpe_str():
    exc = subprocess.CalledProcessError(1, ["/opt/updater-python", "/x/merge-staging-db.py"])
    print("STR", str(exc))
    print("REPR", repr(exc))
    assert False
