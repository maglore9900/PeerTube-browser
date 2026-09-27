"""`resolve_client_address` on the Client backend: which address a request is attributed to, given its peer, its `X-Forwarded-For` and the trusted proxy networks.

- Behind a trusted peer, the hops are walked right to left, trusted ones skipped, and the first untrusted hop is returned, stripped and canonical; a chain trusted end to end gives its leftmost hop. IPv4-mapped v6 addresses are judged by the v4 address they carry.
- An untrusted peer, an unparseable peer, or a trusted peer whose last hop is empty or not an IP gives the peer, as it was passed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "client" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import server as client_server  # noqa: E402


def test_a_trusted_peer_resolves_to_the_rightmost_hop_not_the_forgeable_leftmost():
    assert client_server.resolve_client_address("127.0.0.1", "6.6.6.6, 203.0.113.9", client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "203.0.113.9"  # C1


def test_the_trusted_set_decides_which_hops_are_skipped():
    trusted = client_server.parse_trusted_proxies("127.0.0.1,10.0.0.5")
    assert client_server.resolve_client_address("127.0.0.1", "203.0.113.9, 10.0.0.5", trusted) == "203.0.113.9"  # C1
    # The same chain under the default, where 10.0.0.5 is an untrusted hop and so the answer.
    assert client_server.resolve_client_address("127.0.0.1", "203.0.113.9, 10.0.0.5", client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "10.0.0.5"  # C1


def test_a_chain_trusted_end_to_end_resolves_to_its_leftmost_hop():
    trusted = client_server.parse_trusted_proxies("127.0.0.1,10.0.0.0/8")
    # Three hops, so neither the peer, the rightmost nor the second hop can pass for the leftmost.
    assert client_server.resolve_client_address("127.0.0.1", "10.0.0.7, 10.0.0.6, 10.0.0.5", trusted) == "10.0.0.7"  # C1


def test_ipv4_mapped_addresses_are_judged_by_the_v4_address_they_carry():
    trusted = client_server.DEFAULT_TRUSTED_PROXY_NETWORKS
    assert client_server.resolve_client_address("::ffff:127.0.0.1", "203.0.113.9", trusted) == "203.0.113.9"  # C1
    assert client_server.resolve_client_address("127.0.0.1", "203.0.113.9, ::ffff:127.0.0.1", trusted) == "203.0.113.9"  # C1
    # Unmapping is for the trust check only: the untrusted peer is not handed back as 198.51.100.7.
    assert client_server.resolve_client_address("::ffff:198.51.100.7", "203.0.113.9", trusted) == "::ffff:198.51.100.7"  # C2


def test_a_returned_peer_is_not_canonicalised():
    # Unlike an accepted hop, which comes back as 2001:db8::7.
    assert client_server.resolve_client_address("2001:DB8:0::7", "203.0.113.9", client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "2001:DB8:0::7"  # C2
    # 0:0:0:0:0:0:0:1 is ::1, so it is trusted and walks to a good hop; that puts the next assertion on the bad-last-hop fallback, not the untrusted early return.
    assert client_server.resolve_client_address("0:0:0:0:0:0:0:1", "203.0.113.9", client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "203.0.113.9"  # C1
    assert client_server.resolve_client_address("0:0:0:0:0:0:0:1", "6.6.6.6, not-an-ip", client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "0:0:0:0:0:0:0:1"  # C2


def test_an_accepted_v6_hop_comes_back_canonical():
    assert client_server.resolve_client_address("127.0.0.1", "6.6.6.6, 2001:DB8:0:0::1 ", client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "2001:db8::1"  # C1


@pytest.mark.parametrize("forwarded_for", ["", "203.0.113.9", "6.6.6.6, 203.0.113.9", "203.0.113.9, 127.0.0.1"])
def test_an_untrusted_peer_resolves_to_itself_whatever_it_forwards(forwarded_for):
    assert client_server.resolve_client_address("198.51.100.7", forwarded_for, client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "198.51.100.7"  # C2


@pytest.mark.parametrize("forwarded_for", ["", "   ", "6.6.6.6, not-an-ip", "6.6.6.6, ", "unknown"])
def test_a_trusted_peer_whose_last_hop_is_empty_or_not_an_ip_resolves_to_itself(forwarded_for):
    # 6.6.6.6 sits left of a bad last hop, so a walk that skips the bad hop instead of stopping returns it.
    assert client_server.resolve_client_address("127.0.0.1", forwarded_for, client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "127.0.0.1"  # C2


def test_an_unparseable_peer_resolves_to_itself():
    assert client_server.resolve_client_address("unknown", "203.0.113.9", client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "unknown"  # C2


def test_a_configured_range_replaces_the_loopback_default():
    trusted = client_server.parse_trusted_proxies("10.0.0.0/8")
    assert client_server.resolve_client_address("10.1.2.3", "203.0.113.9", trusted) == "203.0.113.9"  # C1
    # Loopback is trusted only by the default, not in addition to what is configured.
    assert client_server.resolve_client_address("127.0.0.1", "203.0.113.9", trusted) == "127.0.0.1"  # C2
