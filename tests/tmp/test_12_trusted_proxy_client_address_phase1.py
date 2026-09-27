"""`TRUSTED_PROXIES` on the Client backend: what it parses to, and how a malformed one stops startup.

- `parse_trusted_proxies` returns exactly the listed networks, in order, with whitespace and stray commas ignored; a value listing nothing is the `127.0.0.1,::1` default.
- `main()` given a malformed entry raises `SystemExit` naming it, before it swaps the signal handlers or opens `users.db`, so before it binds.
"""
from __future__ import annotations

import signal
import socket
import sys
from ipaddress import ip_network
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "client" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import server as client_server  # noqa: E402

LOOPBACK = (ip_network("127.0.0.1/32"), ip_network("::1/128"))


def test_a_single_range_parses_to_exactly_that_network():
    assert client_server.parse_trusted_proxies("10.0.0.0/8") == (ip_network("10.0.0.0/8"),)  # C1


def test_bare_v4_and_v6_addresses_parse_to_host_networks():
    # Off the default, and v6 before v4 so a parse that sorts its output fails too.
    assert client_server.parse_trusted_proxies("2001:db8::1,192.0.2.7") == (ip_network("2001:db8::1/128"), ip_network("192.0.2.7/32"))  # C1


def test_whitespace_and_stray_commas_are_tolerated():
    parsed = client_server.parse_trusted_proxies(" 10.0.0.0/8 ,, 192.0.2.1 , 2001:db8::/32,")
    assert parsed == (ip_network("10.0.0.0/8"), ip_network("192.0.2.1/32"), ip_network("2001:db8::/32"))  # C1


@pytest.mark.parametrize("value", ["", "  ", ",", " , "])
def test_a_value_listing_no_entries_is_the_loopback_default(value):
    assert client_server.parse_trusted_proxies(value) == LOOPBACK  # C1


@pytest.fixture
def startup(monkeypatch, tmp_path):
    """main() pointed at a port held by a listener here, so a startup that gets as far as binding fails instead of serving forever; yields the users.db directory it would create."""
    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    held.listen()
    # A valid argv, so argparse cannot be the SystemExit.
    monkeypatch.setattr(sys, "argv", ["server.py", "--host", "127.0.0.1", "--port", str(held.getsockname()[1])])
    # Keeps a startup that gets past the check off the worktree's real users.db.
    monkeypatch.setattr(client_server, "ROOT_DIR", tmp_path)
    before = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    try:
        yield (tmp_path / client_server.DEFAULT_USERS_DB_PATH).parent
    finally:
        # A startup that failed at bind leaves its handlers installed in this process.
        signal.signal(signal.SIGINT, before[0])
        signal.signal(signal.SIGTERM, before[1])
        held.close()


def test_a_valid_value_gets_main_as_far_as_swapping_signals_and_creating_the_db(startup, monkeypatch):
    # Control: proves the two absences below would be seen if startup got past the check.
    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1, 10.0.0.0/8")
    before = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    with pytest.raises(OSError):
        client_server.main()
    assert (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)) != before
    assert startup.is_dir()


@pytest.mark.parametrize("entry", ["10.0.0.0/33", "not-an-ip", "300.1.1.1"])
def test_a_malformed_entry_stops_main_naming_it_before_signals_or_the_db(entry, startup, monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", f"127.0.0.1, {entry}")
    before = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    with pytest.raises(SystemExit) as exc:
        client_server.main()
    assert entry in str(exc.value.code)  # C2
    assert (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)) == before
    assert not startup.exists()
