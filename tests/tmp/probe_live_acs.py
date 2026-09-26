"""Probe: the clause-free criteria (AC9, AC11, AC12) against the live Client backend on :7072.

Mints one profile on the live service and deletes it again at the end.
"""
import json
import sqlite3
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:7072"


def call(method, path, headers=None, data=None):
    req = urllib.request.Request(BASE + path, data=data, method=method)
    for name, value in (headers or {}).items():
        req.add_header(name, value)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


conn = sqlite3.connect("file:client/backend/db/users.db?mode=ro", uri=True)
print("AC9 local-user rows:",
      conn.execute("SELECT COUNT(*) FROM users WHERE user_id='local-user'").fetchone()[0],
      conn.execute("SELECT COUNT(*) FROM likes WHERE user_id='local-user'").fetchone()[0])
conn.close()

status, headers, _ = call("OPTIONS", "/api/user-profile/reset")
print("AC12 preflight:", status, headers.get("access-control-allow-headers"))

status, _, body = call("POST", "/api/profile", {"content-type": "application/json"}, b"{}")
key = json.loads(body)["key"]
status, _, body = call("POST", "/api/user-profile/reset",
                       {"content-type": "application/json", "x-profile-key": key}, b"{not json")
print("AC11 malformed reset body:", status, body.decode()[:80])
status, _, _ = call("POST", "/api/profile/delete",
                    {"content-type": "application/json", "x-profile-key": key}, b"{}")
print("cleanup delete:", status)
