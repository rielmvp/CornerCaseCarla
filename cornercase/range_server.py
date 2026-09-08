"""Static file server with HTTP Range support (required for <video> playback)."""
import base64, os, re, sys, http.server, socketserver

# Optional HTTP basic auth. Set DEMO_USER and DEMO_PASS before exposing this
# server through a public tunnel; with them unset the server stays open, which
# is fine for localhost/VS Code port-forward use only.
_USER = os.environ.get("DEMO_USER")
_PASS = os.environ.get("DEMO_PASS")
_AUTH = ("Basic " + base64.b64encode(f"{_USER}:{_PASS}".encode()).decode()) if _USER and _PASS else None

ROOT = sys.argv[2] if len(sys.argv) > 2 else "."
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8899

class H(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _authed(self):
        if _AUTH is None:
            return True
        hdr = self.headers.get("Authorization", "")
        # constant-time compare to avoid leaking the credential by timing
        import hmac
        if hmac.compare_digest(hdr, _AUTH):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="CARLA demo"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def do_GET(self):
        if not self._authed():
            return
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not rng or not os.path.isfile(path):
            return super().do_GET()
        m = re.match(r"bytes=(\d*)-(\d*)", rng.strip())
        if not m:
            return super().do_GET()
        size = os.path.getsize(path)
        start = int(m.group(1)) if m.group(1) else 0
        end = int(m.group(2)) if m.group(2) else size - 1
        end = min(end, size - 1)
        if start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return
        length = end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        with open(path, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def log_message(self, *a):
        pass

class S(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

S(("0.0.0.0", PORT), H).serve_forever()
