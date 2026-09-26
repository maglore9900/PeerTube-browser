"""Probe: can a client bind 127.0.0.2 and reach a server on 127.0.0.1, and what peer does the server see?"""
import http.client
import http.server
import threading

seen = []


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        seen.append(self.client_address[0])
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
for src in ("127.0.0.1", "127.0.0.2"):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], source_address=(src, 0))
    c.request("GET", "/")
    c.getresponse()
    c.close()
print(seen)
srv.shutdown()
