import http.client
import http.server
import threading


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


def test_probe_close_reconnects():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    client = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    ports = []
    for _ in range(2):
        client.request("GET", "/")
        ports.append(client.sock.getsockname()[1])
        client.getresponse().read()
    print("PORTS", ports)
    srv.shutdown()
    assert False
