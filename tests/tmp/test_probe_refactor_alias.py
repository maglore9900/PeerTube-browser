import ipaddress
import sys


def test_probe_runtime_union_alias():
    print("version", sys.version)
    alias = tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]
    print("alias", alias)
    assert alias is not None
