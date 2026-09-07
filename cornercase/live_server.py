"""Static site + a small job API for live runs.

  python cornercase/live_server.py [port] [site_dir]     (defaults: 8900, outputs/site)

GET  /                      the generated pages (Range-capable, so <video> works)
POST /api/run               {scenario, model, seed, steps} -> {id}
GET  /api/status?id=...     progress JSON published by the worker
GET  /api/health            is a worker resident?
GET  /live/out/<file>       videos of finished live runs

Auth: set DEMO_USER/DEMO_PASS before exposing through a public tunnel.
"""
import base64, hmac, json, os, re, sys, time, uuid, http.server, socketserver

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

ROOT = sys.argv[2] if len(sys.argv) > 2 else paths.SITE
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8900
LIVE = os.environ.get("LIVE_QUEUE") or paths.LIVE
_U, _P = os.environ.get("DEMO_USER"), os.environ.get("DEMO_PASS")
_AUTH = ("Basic " + base64.b64encode(f"{_U}:{_P}".encode()).decode()) if _U and _P else None
JOBS, STATUS = os.path.join(LIVE, "jobs"), os.path.join(LIVE, "status")
SAFE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class H(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass

    def _auth_ok(self):
        if _AUTH is None:
            return True
        if hmac.compare_digest(self.headers.get("Authorization", ""), _AUTH):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="CARLA demo"')
        self.send_header("Content-Length", "0"); self.end_headers()
        return False

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(b)

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def do_POST(self):
        if not self._auth_ok(): return
        if self.path.split("?")[0] != "/api/run":
            return self._json({"error": "not found"}, 404)
        n = int(self.headers.get("Content-Length", 0) or 0)
        try: req = json.loads(self.rfile.read(n) or b"{}")
        except Exception: return self._json({"error": "bad json"}, 400)
        scen, model = str(req.get("scenario", "")), str(req.get("model", "1"))
        if not SAFE.match(scen):
            return self._json({"error": "bad scenario"}, 400)
        if model not in ("1", "1.5"):
            return self._json({"error": "bad model"}, 400)
        if not os.path.exists(paths.scenario_file(scen)):
            return self._json({"error": "unknown scenario"}, 404)
        try:
            seed = int(req.get("seed", 42)); steps = int(req.get("steps", 120))
        except Exception:
            return self._json({"error": "bad seed/steps"}, 400)
        steps = max(20, min(240, steps))
        jid = f"{scen}_{'r1' if model=='1' else 'v15'}_{seed}_{uuid.uuid4().hex[:6]}"
        os.makedirs(JOBS, exist_ok=True); os.makedirs(STATUS, exist_ok=True)
        with open(os.path.join(STATUS, jid + ".json"), "w") as f:
            json.dump({"phase": "queued", "step": 0, "total": steps,
                       "scenario": scen, "seed": seed, "updated": time.time()}, f)
        tmp = os.path.join(JOBS, jid + ".json.tmp")
        with open(tmp, "w") as f:
            json.dump({"id": jid, "scenario": scen, "model": model,
                       "seed": seed, "steps": steps,
                       "mode": "live"}, f)
        os.replace(tmp, os.path.join(JOBS, jid + ".json"))
        pend = len([x for x in os.listdir(JOBS) if x.endswith(".json")])
        return self._json({"id": jid, "queued": pend})

    def do_GET(self):
        if not self._auth_ok(): return
        p = self.path.split("?")[0]
        if p == "/api/health":
            hb = os.path.join(LIVE, "worker_ready")
            ready = os.path.exists(hb) and (time.time() - os.path.getmtime(hb)) < 90
            pend = len([x for x in os.listdir(JOBS)]) if os.path.isdir(JOBS) else 0
            return self._json({"worker_ready": ready, "queued": pend})
        if p == "/api/status":
            q = dict(x.split("=", 1) for x in self.path.partition("?")[2].split("&") if "=" in x)
            jid = q.get("id", "")
            if not SAFE.match(jid): return self._json({"error": "bad id"}, 400)
            f = os.path.join(STATUS, jid + ".json")
            if not os.path.exists(f): return self._json({"phase": "unknown"}, 404)
            try: return self._json(json.load(open(f)))
            except Exception: return self._json({"phase": "queued"})
        # the live queue lives outside the site dir; serve its videos explicitly
        if p.startswith("/live/out/"):
            fn = os.path.basename(p)
            if not SAFE.match(fn.replace(".mp4", "")): return self._json({"error": "bad"}, 400)
            full = os.path.join(LIVE, "out", fn)
            if not os.path.exists(full): return self._json({"error": "not found"}, 404)
            return self._send_file(full, "video/mp4")
        return self._range_get()

    def _send_file(self, full, ctype):
        size = os.path.getsize(full)
        rng = self.headers.get("Range")
        m = re.match(r"bytes=(\d*)-(\d*)", rng.strip()) if rng else None
        if not m:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size)); self.end_headers()
            with open(full, "rb") as fh:
                while (c := fh.read(65536)): self.wfile.write(c)
            return
        s = int(m.group(1)) if m.group(1) else 0
        e = int(m.group(2)) if m.group(2) else size - 1
        e = min(e, size - 1)
        self.send_response(206)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Range", f"bytes {s}-{e}/{size}")
        self.send_header("Content-Length", str(e - s + 1)); self.end_headers()
        with open(full, "rb") as fh:
            fh.seek(s); rem = e - s + 1
            while rem > 0 and (c := fh.read(min(65536, rem))):
                self.wfile.write(c); rem -= len(c)

    def _range_get(self):
        path = self.translate_path(self.path)
        rng = self.headers.get("Range")
        if not rng or not os.path.isfile(path):
            return super().do_GET()
        return self._send_file(path, self.guess_type(path))


class S(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    # Local only by default; scripts/demo.sh exposes it through a tunnel when asked.
    host = os.environ.get("BIND_HOST", "127.0.0.1")
    os.makedirs(ROOT, exist_ok=True)
    print(f"serving {ROOT} on {host}:{PORT} (auth={'on' if _AUTH else 'OFF'})", flush=True)
    S((host, PORT), H).serve_forever()
