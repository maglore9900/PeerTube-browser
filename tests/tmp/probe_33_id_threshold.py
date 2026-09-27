from test_33_metadata_id_threshold_precedence_phase1 import BULK, BULK_ERRORED, BULK_SIZE, _add, _bulk, _row, conn, metadata  # noqa: F401


def _fixed(conn, entries, threshold):
    result = {}
    for batch in metadata._chunk(entries, 450):
        conditions = " OR ".join(["(v.video_id = ? AND v.instance_domain = ?)"] * len(batch))
        params = [value for entry in batch for value in (entry["video_id"], entry["instance_domain"])]
        for row in metadata._select_metadata(conn, f"({conditions})", params, threshold):
            result[metadata.like_key(row)] = row
    return result


def test_probe(conn):
    for i in range(BULK_SIZE):
        _add(conn, _bulk(i), error_count=5 if i == BULK_ERRORED else 0)
    conn.commit()
    entries = [{"video_id": _bulk(i)[0], "instance_domain": BULK} for i in range(BULK_SIZE)]
    current_none = metadata.fetch_metadata_by_ids(conn, entries, error_threshold=None)
    print("current none: len", len(current_none), "c455 row ok", current_none.get("c455::bulk.example") == _row(*_bulk(455)))
    fixed3 = _fixed(conn, entries, 3)
    fixed_none = _fixed(conn, entries, None)
    print("fixed 3: len", len(fixed3), "c455 in", "c455::bulk.example" in fixed3, "c452 ok", fixed3.get("c452::bulk.example") == _row(*_bulk(452)))
    print("fixed none: len", len(fixed_none), "c455 row ok", fixed_none.get("c455::bulk.example") == _row(*_bulk(455)))
    assert False
