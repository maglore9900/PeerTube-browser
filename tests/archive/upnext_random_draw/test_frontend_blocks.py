"""Retired from `tests/active/test_frontend_blocks.py` in build 09-similars-diversity (plan 19), step 8.

It conflicts with that build's phase 3 C1: an up-next page is now a random score-weighted draw. `in_upnext` is taken from one keyless 8-row draw, and the node runner fetches up-next again and asserts that channel is on the fresh draw (old line 120), which fails or flakes. Its search-side assertions do not conflict, but they sit in the same test and cannot be split off without a rewrite. The pinned rewrite in plan §7g was never written; issue 35 tracks a replacement. Kept readable here. It depends on `_bundle`, `_run` and `_seed_and_targets` in the active file, so a bare `pytest` run skips it.

The retired module docstring bullet read:

- After `blockVideoSource` for a video's channel, the rows `fetchSimilarVideosPayload` (up
  next) and `fetchSearchResults` return omit that channel, where the same calls before the
  block included it: both fetches send the stored key, and search does not serve a cached
  pre-block page.
"""
import pytest

pytestmark = pytest.mark.skip(reason="retired test, kept for reference")


def test_a_channel_blocked_through_the_module_leaves_the_upnext_and_search_rows_it_fetches(
        engine_client, tmp_path):
    runner = _bundle(tmp_path, engine_client.base)
    seed, in_upnext, in_search = _seed_and_targets(engine_client)
    upnext_target = [in_upnext["instance_domain"], in_upnext["channel_id"]]
    search_target = [in_search["instance_domain"], in_search["channel_id"]]

    out = _run(runner, engine_client.base, seed, [
        "create", "upnext", "search",
        f"block|{in_upnext['video_uuid']}|{in_upnext['instance_domain']}",
        f"block|{in_search['video_uuid']}|{in_search['instance_domain']}",
        "upnext", "search",
    ])
    _key, before_upnext, before_search, _b1, _b2, after_upnext, after_search = out

    assert upnext_target in before_upnext["ok"]  # the channel was on the page before the block
    assert search_target in before_search["ok"]
    assert after_upnext["ok"] and after_search["ok"]  # the pages still have rows
    assert upnext_target not in after_upnext["ok"]
    assert search_target not in after_search["ok"]
