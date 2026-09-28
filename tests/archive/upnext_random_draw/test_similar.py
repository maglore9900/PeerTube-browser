"""Retired from `tests/active/test_similar.py` in build 09-similars-diversity (plan 19), step 8.

It conflicts with that build's phase 3 C1: an up-next page is now a random score-weighted draw from the top 4 x limit rows of the pool, so a plain page does not repeat (the control at its old line 174) and a limit=16 page does not start with the limit=8 page (line 179). The seeded-and-floored rewrite in plan §7b was never written; issue 35 tracks a replacement. Kept readable here. It depends on `_upnext_path` and `UPNEXT_PAGE` in the active file, so a bare `pytest` run skips it.

The retired module docstring bullet read:

- For a seed whose ranked pool fills two 8-row pages, an up-next request excluding the previous
  8-row page, or every other row of it, returns the next 8 rows of that ranked pool with the
  excluded rows removed, where the same request without `exclude` returns that page again.
"""
import pytest

pytestmark = pytest.mark.skip(reason="retired test, kept for reference")

# Seeds whose up-next pool was 19 and 17 deep when measured.
UPNEXT_SEED_QUERIES = ("linux", "cooking")


def _key_list(rows: list[dict]) -> list[tuple[str, str]]:
    return [(r["video_id"], r["instance_domain"]) for r in rows]


@pytest.mark.parametrize("query", UPNEXT_SEED_QUERIES)
def test_upnext_excluding_the_previous_page_returns_a_full_page_of_other_videos(engine, query):
    path = _upnext_path(engine, query)
    status, first = engine.request("POST", path, body={})
    assert status == 200 and len(first["rows"]) == UPNEXT_PAGE, first
    previous = _key_list(first["rows"])
    status, plain = engine.request("POST", path, body={})
    assert status == 200 and _key_list(plain["rows"]) == previous, "control: the plain page does not repeat"
    # The seed's ranked pool two pages deep; the first page is its head.
    status, deep = engine.request(
        "POST", path.replace(f"limit={UPNEXT_PAGE}", f"limit={UPNEXT_PAGE * 2}"), body={})
    ranked = _key_list(deep["rows"])
    assert status == 200 and len(ranked) == UPNEXT_PAGE * 2 and ranked[:UPNEXT_PAGE] == previous, \
        "control: pool too shallow"

    # The whole previous page, and every other row of it, which offset paging would not reproduce.
    for excluded in (previous, previous[0::2]):
        exclude = [{"id": video_id, "host": host} for video_id, host in excluded]
        status, page = engine.request("POST", path, body={"exclude": exclude})
        assert status == 200, page

        expected = [key for key in ranked if key not in set(excluded)][:UPNEXT_PAGE]
        assert _key_list(page["rows"]) == expected, (excluded, _key_list(page["rows"]))
