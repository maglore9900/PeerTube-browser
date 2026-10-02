import http.client
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

seen = []


class Echo(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        seen.append(dict(self.headers.items()))
        self.send_response(204)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def test_probe_http_client_headers():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Echo)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        conn.request("GET", "/x", headers={"X-Request-ID": "a" * 65})
        conn.getresponse().read()
        conn.close()
    finally:
        srv.shutdown()
        srv.server_close()
    print("SEEN", seen)
    assert False
