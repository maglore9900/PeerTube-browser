from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest

CHECKPOINT = Path(__file__).resolve().parent / "test_45_trending_from_source_instances_phase2.py"
spec = importlib.util.spec_from_file_location("checkpoint_phase2", CHECKPOINT)
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)
rv = cp.random_videos

TRENDING = """
    t.rank ASC,
    t.likes DESC,
    t.views DESC,
    t.video_id DESC,
    t.instance_domain DESC
"""
SOURCE = {
    "trending": """trending_ranks t
          CROSS JOIN video_embeddings e
            ON e.video_id = t.video_id AND e.instance_domain = t.instance_domain""",
    "popular": "video_embeddings e",
    "recent": "video_embeddings e",
}


@pytest.fixture
def planned(monkeypatch):
    order_by = {"trending": TRENDING, "popular": rv.ORDERED_FEED_ORDER_BY["popular"], "recent": rv.ORDERED_FEED_ORDER_BY["recent"]}
    monkeypatch.setattr(rv, "ORDERED_FEED_ORDER_BY", order_by)
    monkeypatch.setattr(rv, "ORDERED_FEED_SOURCE", SOURCE, raising=False)
    src = inspect.getsource(rv.fetch_ordered_page).replace("order_by = ORDERED_FEED_ORDER_BY[order]", "order_by = ORDERED_FEED_ORDER_BY[order]\n    source = ORDERED_FEED_SOURCE[order]").replace("FROM video_embeddings e", "FROM {source}")
    namespace = dict(vars(rv))
    exec(src, namespace)
    monkeypatch.setattr(rv, "fetch_ordered_page", namespace["fetch_ordered_page"])
    monkeypatch.setattr(rv, "fetch_popular_videos", lambda conn, limit, error_threshold=None, include_nsfw=True: rv.fetch_ordered_page(conn, "trending", limit, 0, error_threshold, include_nsfw))


@pytest.mark.parametrize("ranks_index", (True, False))
@pytest.mark.parametrize("threshold,include_nsfw", cp.FILTERS)
def test_pages(planned, tmp_path, threshold, include_nsfw, ranks_index):
    (tmp_path / "w").mkdir()
    (tmp_path / "p").mkdir()
    cp.test_trending_pages_walk_ranked_catalogue_rows_by_rank_then_listed_likes_views_video_id_and_domain(tmp_path / "w", threshold, include_nsfw, ranks_index)
    cp.test_the_popular_pool_of_size_n_is_the_first_n_rows_of_the_trending_order_under_the_same_filters(tmp_path / "p", threshold, include_nsfw)


def test_rest(planned, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "c").mkdir()
    cp.test_a_trending_page_holds_only_ranked_catalogue_rows(tmp_path / "a")
    cp.test_an_empty_ranks_table_gives_an_empty_trending_page_and_an_empty_popular_pool(tmp_path / "b")
    cp.test_a_trending_page_walks_the_ranks_index_without_sorting(tmp_path / "c")
    cp.test_the_ordered_feeds_are_trending_popular_and_recent_each_with_a_source()


def test_rank_only_mutant_fails(planned, tmp_path, monkeypatch):
    monkeypatch.setitem(rv.ORDERED_FEED_ORDER_BY, "trending", "t.rank ASC")
    cp.test_trending_pages_walk_ranked_catalogue_rows_by_rank_then_listed_likes_views_video_id_and_domain(tmp_path, None, True, True)
    print("rank-only passes with the index")
    (tmp_path / "x").mkdir()
    with pytest.raises(AssertionError):
        cp.test_trending_pages_walk_ranked_catalogue_rows_by_rank_then_listed_likes_views_video_id_and_domain(tmp_path / "x", None, True, False)


def test_crawled_likes_mutant_fails(planned, tmp_path, monkeypatch):
    monkeypatch.setitem(rv.ORDERED_FEED_ORDER_BY, "trending", "t.rank ASC, v.likes DESC, v.views DESC, v.video_id DESC, v.instance_domain DESC")
    with pytest.raises(AssertionError):
        cp.test_trending_pages_walk_ranked_catalogue_rows_by_rank_then_listed_likes_views_video_id_and_domain(tmp_path, None, True, True)


def test_left_join_mutant_fails(planned, tmp_path, monkeypatch):
    monkeypatch.setitem(SOURCE, "trending", "video_embeddings e LEFT JOIN trending_ranks t ON e.video_id = t.video_id AND e.instance_domain = t.instance_domain")
    with pytest.raises(AssertionError):
        cp.test_a_trending_page_holds_only_ranked_catalogue_rows(tmp_path)


def test_no_domain_key_mutant_fails(planned, tmp_path, monkeypatch):
    monkeypatch.setitem(rv.ORDERED_FEED_ORDER_BY, "trending", "t.rank ASC, t.likes DESC, t.views DESC, t.video_id DESC, t.instance_domain ASC")
    with pytest.raises(AssertionError):
        cp.test_trending_pages_walk_ranked_catalogue_rows_by_rank_then_listed_likes_views_video_id_and_domain(tmp_path, None, True, True)


def test_non_cross_join_plan(planned, tmp_path, monkeypatch):
    monkeypatch.setitem(SOURCE, "trending", "video_embeddings e JOIN trending_ranks t ON e.video_id = t.video_id AND e.instance_domain = t.instance_domain")
    try:
        cp.test_a_trending_page_walks_the_ranks_index_without_sorting(tmp_path)
        print("plain JOIN fragment: plan check passes")
    except AssertionError as exc:
        print("plain JOIN fragment: plan check fails", str(exc)[:300])
