"""Controlled ComfyUI wire fixture; no model downloads or GPU allocation."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import httpx

from vgpu_local.runtime_cli import running
from vgpu_local.runtime_config import initialize
from vgpu_local.runtime_store import RuntimeStore

PROMPT = {"1": {"class_type": "Fixture", "inputs": {"text": "owner workflow"}}}


def wait_for(check, timeout=15):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        result = check()
        if result: return result
        time.sleep(.05)
    raise AssertionError("condition did not become true")


class EngineFixture:
    def __init__(self):
        self.jobs, self.history, self.posts = {}, {}, 0
        self.lose_reply = False
        self.lock = threading.Lock()
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                with fixture.lock:
                    if self.path == "/queue": body = {"queue_running": list(fixture.jobs.values()), "queue_pending": []}
                    elif self.path.startswith("/history/"):
                        job = self.path.removeprefix("/history/")
                        body = {job: fixture.history[job]} if job in fixture.history else {}
                    else: self.send_error(404); return
                self.reply(body)
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/prompt":
                    with fixture.lock:
                        fixture.posts += 1
                        job = body["prompt_id"]
                        fixture.jobs[job] = [0, job, body["prompt"], body["extra_data"], []]
                    if fixture.lose_reply:
                        self.close_connection = True
                        return
                    self.reply({"prompt_id": job, "number": 0, "node_errors": {}})
                elif self.path.endswith("/cancel"):
                    job = self.path.split("/")[-2]
                    found = fixture.finish(job, canceled=True)
                    self.reply({"cancelled": found})
                else: self.send_error(404)
            def reply(self, body):
                data = json.dumps(body).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
    def __enter__(self): self.thread.start(); return self
    def __exit__(self, *args): self.server.shutdown(); self.server.server_close(); self.thread.join()
    def finish(self, job, *, canceled=False):
        with self.lock:
            entry = self.jobs.pop(job, None)
            if not entry: return False
            self.history[job] = {"prompt": entry, "status": {"completed": not canceled,
                "status_str": "error" if canceled else "success",
                "messages": [["execution_interrupted", {}]] if canceled else []},
                "outputs": {} if canceled else {"1": {"text": ["fixture result"]}}}
            return True


def setup(path, engine):
    initialize(path, engine.endpoint)
    store = RuntimeStore(path / "jobs.sqlite3")
    store.install_recipe("fixture", "Test workflow", PROMPT)
    return store


@contextmanager
def service(path):
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    with (path / "test-service.log").open("ab") as log:
        process = subprocess.Popen([sys.executable, "-m", "vgpu_local", "runtime", "serve", "--state", str(path)],
                                   stdout=log, stderr=log, **options)
        try:
            def ready():
                if process.poll() is not None: raise AssertionError((path / "test-service.log").read_text())
                try:
                    info = running(path)
                    result = httpx.get(info["origin"]+"/api/status", headers={"Authorization": "Bearer "+info["token"]}, trust_env=False, timeout=.5)
                    return info if result.status_code == 200 else None
                except (ValueError, httpx.HTTPError): return None
            info = wait_for(ready)
            yield info, process
        finally:
            if process.poll() is None:
                try:
                    httpx.post(info["origin"]+"/api/stop", headers={"Authorization": "Bearer "+info["token"]}, trust_env=False, timeout=5)
                    process.wait(timeout=15)
                except (UnboundLocalError, httpx.HTTPError, subprocess.TimeoutExpired):
                    process.kill(); process.wait(timeout=10)


def submit(info):
    with httpx.Client(base_url=info["origin"], trust_env=False,
                      headers={"Authorization": "Bearer "+info["token"], "Origin": info["origin"]}) as client:
        command = client.post("/api/commands/prepare", json={"action": "start", "recipe_id": "fixture"}).json()
        response = client.post("/api/commands", json={"command": command})
        assert response.status_code == 202, response.text
        return command
