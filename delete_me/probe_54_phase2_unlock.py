import fcntl
import os


def test_unlock(tmp_path):
    lock = tmp_path / "worker.lock"
    held = os.open(lock, os.O_RDONLY | os.O_CREAT)
    mine = os.open(lock, os.O_RDONLY)
    fcntl.flock(held, fcntl.LOCK_EX)
    try:
        fcntl.flock(mine, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print("\nfirst NB on mine: no raise")
    except BlockingIOError:
        print("\nfirst NB on mine: BlockingIOError")
    os.close(held)
    os.close(mine)
    assert False, "probe"
