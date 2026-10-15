import argparse


def test_probe_negative_int_value():
    parser = argparse.ArgumentParser()
    parser.add_argument("--increments", type=int, default=0)
    parser.add_argument("--increment-state", default=None)
    print("PROBE", parser.parse_args(["--increments", "-1", "--increment-state", "/x/p.json"]))
    assert False
