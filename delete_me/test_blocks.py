"""Retired from `tests/active/test_blocks.py` in build 09-similars-diversity (plan 19), step 8.

Retired: the two up-next cases (`/recommendations`, `/videos/similar`) of `test_blocked_channel_and_account_leave_only_the_blocking_profile_s_page`, whose `search` case stays active, and `test_an_upnext_page_stays_full_after_blocks_remove_rows_from_it`. Both conflict with that build's phase 3 C1: an up-next page is now a random score-weighted draw, so `_surface` no longer gives "the same page on every call".

- The surfaces test takes targets from one keyless draw and asserts they are present on fresh keyless and bystander draws (old lines 182-183), which fails or flakes.
- The stays-full test was still green, but vacuously about half the time. It blocks `keyless[:3]` from one draw and checks absence and a full page on another. A probe (12 trials per route, music seed) saw none of the three blocked channels in the blocker's 16-row over-fetched Engine draw in 6 of 12 trials on each route. In those runs neither the filter nor the refill does anything.

The pinned rewrite in plan §7e was never written; issue 35 tracks replacements. Kept readable here. It depends on `_rows`, `_mint`, `_block`, `_channel`, `_distinct` and `SEARCH` in the active file, so a bare `pytest` run skips it.

The retired module docstring bullets read:

- Through the read gateway, a profile's up-next (`/recommendations`, `/videos/similar`) and
  search pages leave out its blocked channel and account, while keyless requests and other
  profiles still receive them.
- An up-next page for a profile with blocks is refilled to the requested size from the
  Client's over-fetch, with no blocked target in it.
"""
import pytest

pytestmark = pytest.mark.skip(reason="retired test, kept for reference")

PAGE = 8


def _upnext(route: str, seed: dict, limit: int) -> str:
    return f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={limit}"


def _surface(client, surface: str) -> tuple[str, str]:
    """The method and path of one page of the named surface, the same page on every call."""
    if surface == "search":
        return "GET", SEARCH
    seed = _rows(client, "GET", SEARCH)[0]
    return "POST", _upnext(surface, seed, PAGE)


@pytest.mark.parametrize("surface", ["/recommendations", "/videos/similar"])
def test_blocked_channel_and_account_leave_only_the_blocking_profile_s_page(engine_client, surface):
    method, path = _surface(engine_client, surface)
    keyless = _rows(engine_client, method, path)

    # Both targets are taken from this very page, and share no channel or account, so each
    # block is seen on its own.
    blocked_channel = keyless[0]
    blocked_account = _distinct(keyless, blocked_channel)
    unrelated = _distinct(list(reversed(keyless)), blocked_channel, blocked_account)

    blocker = _mint(engine_client)
    _block(engine_client, blocker, "channel", blocked_channel)
    _block(engine_client, blocker, "account", blocked_account)
    # A second profile holding a block of its own, so its request takes the filtering path too.
    bystander = _mint(engine_client)
    _block(engine_client, bystander, "channel", unrelated)

    def hit(rows: list[dict]) -> tuple[bool, bool]:
        return (any(_channel(r) == _channel(blocked_channel) for r in rows),
                any(r["account_url"] == blocked_account["account_url"] for r in rows))

    blocker_rows = _rows(engine_client, method, path, blocker)
    assert blocker_rows  # the blocker still gets results
    assert not hit(blocker_rows)[0]  # blocked channel absent
    assert not hit(blocker_rows)[1]  # blocked account absent

    assert hit(_rows(engine_client, method, path)) == (True, True)  # keyless still has both
    assert hit(_rows(engine_client, method, path, bystander)) == (True, True)  # second profile too


def _deep_seed(client, route: str) -> dict:
    """A seed whose pool on `route` holds at least a page plus three rows."""
    for seed in _rows(client, "GET", SEARCH):
        if len(_rows(client, "POST", _upnext(route, seed, 2 * PAGE))) >= PAGE + 3:
            return seed
    pytest.fail(f"no search result seeds a {route} pool of PAGE + 3 rows")


@pytest.mark.parametrize("route", ["/recommendations", "/videos/similar"])
def test_an_upnext_page_stays_full_after_blocks_remove_rows_from_it(engine_client, route):
    seed = _deep_seed(engine_client, route)
    keyless = _rows(engine_client, "POST", _upnext(route, seed, PAGE))
    assert len(keyless) == PAGE  # control: the Engine fills the page

    key = _mint(engine_client)
    blocked = keyless[:3]
    for row in blocked:
        _block(engine_client, key, "channel", row)
    blocked_channels = {_channel(r) for r in blocked}

    rows = _rows(engine_client, "POST", _upnext(route, seed, PAGE), key)
    assert len(rows) == PAGE, len(rows)
    assert not blocked_channels & {_channel(r) for r in rows}
