#!/usr/bin/env python3
"""Web app Upscale2K - server HTTP thuan stdlib, hang doi xu ly tuan tu."""
import json
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from engine import upscale_video

BASE = os.path.dirname(os.path.abspath(__file__))
JOBS = os.path.join(BASE, "jobs")
os.makedirs(JOBS, exist_ok=True)
jobs = {}          # job_id -> dict
queue = []         # job_id theo thu tu
lock = threading.Lock()


def worker():
    while True:
        job = None
        with lock:
            for jid in queue:
                if jobs[jid]["state"] == "queued":
                    job = jobs[jid]
                    job["state"] = "processing"
                    break
        if job is None:
            time.sleep(0.5)
            continue

        def cb(done, total, job=job):
            job["done"] = done
            job["total"] = total

        try:
            info = upscale_video(job["input"], job["output"], job["mode"], cb)
            job["info"] = info
            job["state"] = "done"
        except Exception as e:  # noqa: BLE001
            job["state"] = "error"
            job["message"] = str(e)[:300]


def parse_multipart(body, boundary):
    """Tra ve dict field -> (filename|None, bytes). Du dung cho form cua app."""
    parts = {}
    delimiter = b"--" + boundary
    for chunk in body.split(delimiter):
        if not chunk or chunk in (b"--\r\n", b"--"):
            continue
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        if chunk.endswith(b"\r\n"):
            chunk = chunk[:-2]
        if chunk.endswith(b"--"):
            chunk = chunk[:-2]
        head, _, data = chunk.partition(b"\r\n\r\n")
        m = re.search(rb'name="([^"]+)"', head)
        if not m:
            continue
        name = m.group(1).decode()
        fm = re.search(rb'filename="([^"]*)"', head)
        filename = fm.group(1).decode() if fm else None
        parts[name] = (filename, data)
    return parts


PREFIX = "/up"  # app phuc vu them duoi duong dan /up tren ten mien chinh


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _norm(self):
        p = self.path
        if p == PREFIX:
            return "/"
        if p.startswith(PREFIX + "/"):
            return p[len(PREFIX):]
        return p

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.path = self._norm()
        if self.path == "/" or self.path.startswith("/?"):
            html = open(os.path.join(BASE, "index.html"), "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return
        m = re.match(r"^/api/status/([\w-]+)$", self.path)
        if m:
            job = jobs.get(m.group(1))
            if not job:
                return self._json({"error": "not found"}, 404)
            pct = int(job.get("done", 0) * 100 / job["total"]) if job.get("total") else 0
            return self._json({"state": job["state"], "progress": pct,
                               "done": job.get("done", 0), "total": job.get("total", 0),
                               "message": job.get("message", ""), "info": job.get("info")})
        m = re.match(r"^/api/download/([\w-]+)$", self.path)
        if m:
            job = jobs.get(m.group(1))
            if not job or job["state"] != "done":
                return self._json({"error": "not ready"}, 404)
            path = job["output"]
            size = os.path.getsize(path)
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Disposition",
                             'attachment; filename="video_2k.mp4"')
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(path, "rb") as f:
                while True:
                    buf = f.read(1 << 20)
                    if not buf:
                        break
                    self.wfile.write(buf)
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        self.path = self._norm()
        if self.path != "/api/upload":
            return self._json({"error": "not found"}, 404)
        ctype = self.headers.get("Content-Type", "")
        m = re.search(r"boundary=(.+)$", ctype)
        if not m:
            return self._json({"error": "bad content type"}, 400)
        boundary = m.group(1).strip().encode()
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        parts = parse_multipart(body, boundary)
        if "file" not in parts or not parts["file"][0]:
            return self._json({"error": "thieu file video"}, 400)
        filename, data = parts["file"]
        mode = parts.get("mode", (None, b"quality"))[1].decode().strip()
        if mode not in ("fast", "quality"):
            mode = "quality"
        jid = uuid.uuid4().hex[:12]
        jdir = os.path.join(JOBS, jid)
        os.makedirs(jdir, exist_ok=True)
        ext = os.path.splitext(filename)[1].lower() or ".mp4"
        inp = os.path.join(jdir, "input" + ext)
        with open(inp, "wb") as f:
            f.write(data)
        outp = os.path.join(jdir, "output_2k.mp4")
        with lock:
            jobs[jid] = {"id": jid, "state": "queued", "mode": mode,
                         "input": inp, "output": outp, "done": 0, "total": 0,
                         "message": "", "info": None}
            queue.append(jid)
        return self._json({"job_id": jid})


if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    port = int(os.environ.get("PORT", "8321"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
