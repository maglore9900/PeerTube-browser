import sqlite3


def test_row_keys_follow_select_names():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE videos (video_id TEXT, instance_domain TEXT, channel_id TEXT)")
    conn.execute("CREATE TABLE channels (channel_id TEXT, display_name TEXT)")
    conn.execute("INSERT INTO videos VALUES ('a1', 'h.example', 'c1')")
    conn.execute("INSERT INTO channels VALUES ('c1', 'Chan')")
    row = conn.execute(
        """
            SELECT
              v.video_id,
              v.instance_domain,
              c.display_name AS channel_display_name
            FROM videos v
            LEFT JOIN channels c ON c.channel_id = v.channel_id
            WHERE (v.video_id = ?)
        """,
        ["a1"],
    ).fetchone()
    print("KEYS", row.keys())
    print("DICT", dict(row))
    assert False
