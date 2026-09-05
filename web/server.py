"""Dashboard web của AI Hub — chỉ dùng stdlib, 0 dependency, chạy offline.

Bind 127.0.0.1: không mở ra mạng LAN.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HUB = Path(os.environ.get("AIHUB_HOME", "/Users/mac/.aihub"))
sys.path.insert(0, str(HUB / "clients" / "python" / "src"))

from aihub import doctor as D           # noqa: E402
from aihub import fetch as F            # noqa: E402
from aihub import resolve as R          # noqa: E402

WEB = HUB / "web"
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}


def _ram_gb() -> float:
    out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True)
    return int(out.stdout.strip()) / 1e9 if out.stdout.strip() else 0.0


def _ram_free_gb() -> float:
    """RAM khả dụng ≈ free + inactive + speculative (trang có thể thu hồi ngay)."""
    out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
    pg, vals = 16384, {}
    for line in out.splitlines():
        if "page size of" in line:
            pg = int(line.split("page size of")[1].split()[0])
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip().rstrip(".")
            if v.isdigit():
                vals[k.strip()] = int(v)
    free = vals.get("Pages free", 0) + vals.get("Pages inactive", 0) \
        + vals.get("Pages speculative", 0)
    return free * pg / 1e9


def api_status() -> dict:
    store = R.store_root()
    st = os.statvfs(store)
    sizes = {}
    for sub in sorted(p for p in store.iterdir() if p.is_dir()):
        o = subprocess.run(["du", "-sk", str(sub)], capture_output=True, text=True)
        sizes[sub.name] = (int(o.stdout.split()[0]) if o.stdout.strip() else 0) / 1e6

    base = os.environ.get("AIHUB_OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_up, loaded = False, []
    try:
        urllib.request.urlopen(base + "/api/tags", timeout=2)
        ollama_up = True
        with urllib.request.urlopen(base + "/api/ps", timeout=2) as r:
            loaded = [{"name": m["name"], "gb": round(m.get("size", 0) / 1e9, 1)}
                      for m in json.load(r).get("models", [])]
    except Exception:
        pass

    return {
        "store": str(store),
        "store_gb": round(sum(sizes.values()), 1),
        "by_store": {k: round(v, 2) for k, v in sizes.items() if v > 0.01},
        "free_gb": round(st.f_bavail * st.f_frsize / 1e9),
        "ram_gb": round(_ram_gb()),
        "ram_free_gb": round(_ram_free_gb(), 1),
        "ollama_up": ollama_up,
        "loaded": loaded,
    }


def api_models() -> list[dict]:
    # refresh=True: đọc lại registry.toml mỗi lần, để sửa file là thấy ngay.
    # with_disk=True: ĐO dung lượng thật trên đĩa (~0.04 s cho 18 model), không
    # tin con số khai báo trong registry.
    R.load_registry(refresh=True)
    return [m.__dict__ for m in R.list_models(with_disk=True)]


def api_doctor() -> dict:
    rep = D.run()
    return {"rows": [{"level": lv, "name": n, "detail": d} for lv, n, d in rep.rows],
            "failed": rep.failed, "warned": rep.warned}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):            # im lặng
        pass

    # ── helper ────────────────────────────────────────────────────────
    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode())

    def _err(self, msg, code=400):
        self._json({"error": str(msg)}, code)

    # ── GET ───────────────────────────────────────────────────────────
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/api/models":
                return self._json(api_models())
            if u.path == "/api/status":
                return self._json(api_status())
            if u.path == "/api/doctor":
                return self._json(api_doctor())
            if u.path == "/api/search":
                q = (q_.get("q", [""])[0] if (q_ := q) else "").strip()
                if not q:
                    return self._json([])
                return self._json(F.search(q, limit=12))
            if u.path == "/api/preview":
                src = q.get("source", [""])[0]
                inc = q.get("include", None)
                try:
                    res = F.pull(src, include=inc, dry_run=True)
                except (F.PullError, R.ModelNotFound) as e:
                    # Nguồn sai bản chất (vd dán lệnh `gh repo clone`) — tải cũng vô ích.
                    return self._json({"error": str(e), "fatal": True}, 400)
                return self._json(res if isinstance(res, dict) else {"note": str(res)})
            if u.path == "/api/pull":                       # SSE
                return self._sse_pull(q.get("source", [""])[0],
                                      q.get("include") or None)

            # static
            name = "index.html" if u.path == "/" else u.path.lstrip("/")
            f = (WEB / name).resolve()
            if WEB.resolve() not in f.parents or not f.is_file():
                return self._send(404, b"not found", "text/plain")
            return self._send(200, f.read_bytes(),
                              MIME.get(f.suffix, "application/octet-stream"))
        except Exception as e:
            return self._err(e, 500)

    # ── POST / DELETE ─────────────────────────────────────────────────
    def do_POST(self):
        u = urlparse(self.path)
        try:
            if u.path == "/api/serve":
                env = {**os.environ, **R.env_dict()}
                ollama = shutil.which("ollama") or "/usr/local/bin/ollama"
                log = (R.store_root() / "run" / "ollama.log").open("a")
                p = subprocess.Popen([ollama, "serve"], env=env, stdout=log,
                                     stderr=log, start_new_session=True)
                (R.store_root() / "run" / "ollama.pid").write_text(str(p.pid))
                return self._json({"ok": True, "pid": p.pid})
            if u.path == "/api/adopt":
                return self._json({"ok": True, "added": F.adopt_all()})
            if u.path == "/api/stop":
                subprocess.run(["pkill", "-x", "ollama"])
                return self._json({"ok": True})
            return self._err("không có route", 404)
        except Exception as e:
            return self._err(e, 500)

    def do_DELETE(self):
        u = urlparse(self.path)
        if not u.path.startswith("/api/models/"):
            return self._err("không có route", 404)
        name = u.path.rsplit("/", 1)[-1]
        try:
            mi = R.get(name)
            if mi.runtime == "ollama":
                subprocess.run([shutil.which("ollama") or "/usr/local/bin/ollama",
                                "rm", mi.ref], env={**os.environ, **R.env_dict()},
                               check=True)
            elif mi.path:
                p = Path(mi.path)
                tgt = p if mi.store == "whisper" else p.parents[1]
                if tgt.is_dir():
                    shutil.rmtree(tgt, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
            return self._json({"ok": True, "deleted": name})
        except Exception as e:
            return self._err(e, 500)

    # ── SSE tải model ─────────────────────────────────────────────────
    def _sse_pull(self, source: str, include):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def emit(obj):
            try:
                self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                raise SystemExit

        try:
            emit({"status": f"bắt đầu tải {source}"})
            res = F.pull(source, include=include)
            if hasattr(res, "__iter__") and not isinstance(res, (str, Path, dict)):
                for msg in res:                       # stream của Ollama
                    if msg.get("total"):
                        emit({"status": msg.get("status", ""),
                              "pct": round(100 * msg.get("completed", 0) / msg["total"], 1)})
                    else:
                        emit({"status": msg.get("status", "")})
            else:
                emit({"status": f"xong: {res}"})
            emit({"done": True})
        except SystemExit:
            return
        except Exception as e:
            try:
                emit({"error": str(e), "done": True})
            except Exception:
                pass


def serve(port: int = 7860, open_browser: bool = True):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"AI Hub dashboard → {url}   (Ctrl-C để dừng)")
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nđã dừng")
        srv.shutdown()


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 7860)
