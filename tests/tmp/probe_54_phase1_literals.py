"""Probe: run the Step 5 draft's fetch_followed_page shape over the checkpoint's catalogue and print the pages it walks, to check the hand-derived literals."""
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_54_follow_channels_and_accounts_phase1 as cp  # noqa: E402
from data.moderation import filter_rows_by_moderation  # noqa: E402
from data.random_videos import ORDERED_FEED_ORDER_BY, _listing_conditions  # noqa: E402


def draft_page(conn, channels, accounts, cursor, limit, include_nsfw):
    sources = [("v.instance_domain = ? AND v.channel_id = ?", [d, c]) for d, c in channels] + [("v.account_url = ?", [a]) for a in accounts]
    if limit <= 0 or not sources:
        return [], None
    conditions, shared = _listing_conditions(cp.THRESHOLD, include_nsfw)
    conditions.append("v.published_at IS NOT NULL AND v.published_at <= ?")
    shared.append(int(time.time() * 1000))
    if cursor is not None:
        p, vid, dom = cursor
        conditions.append("(v.published_at, v.video_id) <= (?, ?) AND (v.published_at, v.video_id, v.instance_domain) < (?, ?, ?)")
        shared += [p, vid, p, vid, dom]
    where = " AND ".join(conditions)
    rows = []
    for start in range(0, len(sources), 500):
        terms, params = [], []
        for predicate, sp in sources[start:start + 500]:
            terms.append(f"SELECT * FROM (SELECT v.video_id, v.instance_domain, v.channel_id, v.published_at FROM videos v CROSS JOIN video_embeddings e ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain WHERE {predicate} AND {where} ORDER BY {ORDERED_FEED_ORDER_BY['recent']} LIMIT ?)")
            params += sp + shared + [limit]
        params.append(limit * 2)
        rows.extend(dict(r) for r in conn.execute(" UNION ALL ".join(terms) + " ORDER BY published_at DESC, video_id DESC, instance_domain DESC LIMIT ?", params))
    rows.sort(key=lambda r: (r["published_at"], r["video_id"], r["instance_domain"]), reverse=True)
    page, seen = [], set()
    for r in rows:
        k = (r["video_id"], r["instance_domain"])
        if k in seen:
            continue
        seen.add(k)
        page.append(r)
        if len(page) == limit:
            break
    return page, ((page[-1]["published_at"], page[-1]["video_id"], page[-1]["instance_domain"]) if len(page) == limit else None)


def walk(db, follows, limit, include_nsfw=False):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    out, cursor = [], None
    for _ in range(cp.MAX_PAGES):
        page, cursor = draft_page(conn, [tuple(c) for c in follows["channels"]], follows["accounts"], cursor, limit, include_nsfw)
        served, _ = filter_rows_by_moderation(conn, page)
        out.append(([cp.LABEL_OF[(r["video_id"], r["instance_domain"])] for r in served], cursor))
        if cursor is None:
            break
    return out


def test_draft_walks(tmp_path):
    open_db = cp._catalogue(tmp_path / "open.db", blocked=False)
    mod_db = cp._catalogue(tmp_path / "mod.db", blocked=True)
    print("main", walk(open_db, cp.MAIN_FOLLOWS, 4))
    print("nsfw", walk(open_db, cp.MAIN_FOLLOWS, 4, include_nsfw=True))
    print("exact", walk(open_db, cp.MAIN_FOLLOWS, 9))
    print("mod-open", walk(open_db, cp.MODERATION_FOLLOWS, 4))
    print("mod-blocked", walk(mod_db, cp.MODERATION_FOLLOWS, 4))
    batched = {"channels": [cp.MAIN_CHANNELS[0], *cp._dummy_channels(520), *cp.MAIN_CHANNELS[1:]], "accounts": [cp.ACCT_X]}
    print("batched", walk(open_db, batched, 4))
    first_batch_only = {"channels": batched["channels"][:500], "accounts": []}
    print("first batch only (wrong)", walk(open_db, first_batch_only, 4))
