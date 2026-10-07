"""Probe: observe what the drafted tag SQL returns on the checkpoint fixture, before the phase is built."""
import json
import subprocess
import textwrap

from test_search_tags import ENGINE_PY, SERVER_DIR, _statements

_PROBE = textwrap.dedent(
    """
    import json, sqlite3, sys
    conn = sqlite3.connect(":memory:")
    for sql, params in json.loads(sys.argv[1]):
        conn.execute(sql, params)
    TRIM = "' ' || char(9, 10, 13)"
    MATCH = f\"\"\"EXISTS (SELECT 1 FROM json_each(CASE WHEN json_valid(v.tags_json) THEN CASE json_type(v.tags_json) WHEN 'array' THEN v.tags_json ELSE '[]' END ELSE '[]' END) j
      WHERE j.type = 'text' AND lower(trim(j.value, {TRIM})) = lower(trim(?, {TRIM})))\"\"\"
    out = {"lower": conn.execute("select lower('MÚSICA')").fetchone()[0], "sqlite": sqlite3.sqlite_version}
    for phrase in ['linux', 'linux mint', 'música', 'a b']:
        out["fts:" + phrase] = [r[0] for r in conn.execute("SELECT v.video_id FROM videos_fts f JOIN videos v ON v.rowid=f.rowid WHERE videos_fts MATCH ?", ['tags_json : "' + phrase + '"'])]
    out["rowid_order"] = [r[0] for r in conn.execute(f"SELECT v.video_id FROM videos v WHERE {MATCH} ORDER BY v.rowid", ['linux'])]
    for tag in ['\\t LINUX \\n', 'linux', 'linux mint', 'música', 'MÚSICA', '???', 'a"b']:
        out["exact:" + tag] = [r[0] for r in conn.execute(f"SELECT v.video_id FROM videos v WHERE {MATCH} ORDER BY published_at DESC", [tag])]
    out["trim_row"] = [list(r) for r in conn.execute("SELECT v.rowid, v.tags_json, f.tags_json FROM videos v JOIN videos_fts f ON f.rowid = v.rowid WHERE v.video_id IN ('TRIM','L1')")]
    conn.execute("CREATE VIRTUAL TABLE vocab USING fts5vocab(videos_fts, 'instance')")
    out["vocab"] = [list(r) for r in conn.execute("SELECT term, doc, col FROM vocab WHERE term LIKE '%linux%'")]
    try:
        conn.execute("SELECT count(*) FROM videos v, json_each(v.tags_json)").fetchone()
        out["bare_json_each"] = "ok"
    except Exception as exc:
        out["bare_json_each"] = repr(exc)
    print(json.dumps(out, ensure_ascii=False))
    """
)


def test_probe():
    proc = subprocess.run([str(ENGINE_PY), "-c", _PROBE, json.dumps(_statements())], capture_output=True, text=True, timeout=120)
    print(proc.stdout, proc.stderr)
    assert False, proc.stdout + proc.stderr
