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


def listener_addresses(pid, port):
    """Inspect the actual OS listener owned by this qualification process."""
    if sys.platform == "win32":
        script = (f"@(Get-NetTCPConnection -OwningProcess {int(pid)} -State Listen -LocalPort {int(port)} "
                  "| Select-Object -ExpandProperty LocalAddress) | ConvertTo-Json -Compress")
        value = json.loads(subprocess.check_output(["powershell", "-NoProfile", "-Command", script],
                            text=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=15))
        return value if isinstance(value, list) else [value]
    if sys.platform.startswith("linux"):
        import os
        import socket
        inodes = set()
        for p in Path(f"/proc/{int(pid)}/fd").iterdir():
            try: target = os.readlink(p)
            except FileNotFoundError: continue
            if target.startswith("socket:["): inodes.add(target[8:-1])
        addresses = []
        for name, family in (("tcp", socket.AF_INET), ("tcp6", socket.AF_INET6)):
            for line in Path(f"/proc/{int(pid)}/net/{name}").read_text().splitlines()[1:]:
                fields = line.split()
                address, bound_port = fields[1].split(":")
                if fields[3] == "0A" and int(bound_port, 16) == port and fields[9] in inodes:
                    packed = bytes.fromhex(address)
                    packed = b"".join(packed[i:i+4][::-1] for i in range(0, len(packed), 4))
                    addresses.append(socket.inet_ntop(family, packed))
        return addresses
    raise RuntimeError("listener inspection not implemented for this qualification platform")


def crash_runtime(info, launcher):
    import os
    import signal
    # Windows venv python.exe is a redirector: its PID differs from the server.
    # Kill only the runtime identified in this test's private, freshly created state.
    os.kill(info["pid"], signal.SIGTERM if sys.platform == "win32" else signal.SIGKILL)
    launcher.wait(timeout=10)


class EngineFixture:
    def __init__(self):
        self.jobs, self.history, self.posts = {}, {}, 0
        # Prompts in ComfyUI's pending queue. Canceling one dequeues it without
        # any history, as ComfyUI's /api/jobs/{id}/cancel does.
        self.waiting = set()
        self.lose_reply = False
        self.lock = threading.Lock()
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                with fixture.lock:
                    if self.path == "/queue": body = {
                        "queue_running": [entry for job, entry in fixture.jobs.items() if job not in fixture.waiting],
                        "queue_pending": [entry for job, entry in fixture.jobs.items() if job in fixture.waiting]}
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
                    with fixture.lock:
                        dequeued = job in fixture.waiting and fixture.jobs.pop(job, None) is not None
                        fixture.waiting.discard(job)
                    self.reply({"cancelled": dequeued or fixture.finish(job, canceled=True)})
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
            self.waiting.discard(job)
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
