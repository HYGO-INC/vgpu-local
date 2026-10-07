import json
import os
from pathlib import Path
import subprocess
import sys
import time
import webbrowser

import httpx

from .runtime_config import DEFAULT_STATE, initialize, load
from .runtime_store import RuntimeStore


def register(commands):
    runtime = commands.add_parser("runtime", help="Optional background local engine console")
    sub = runtime.add_subparsers(dest="runtime_action", required=True)
    for action in ("init", "start", "serve", "status", "open", "stop", "add-recipe"):
        command = sub.add_parser(action)
        command.add_argument("--state", type=Path, default=DEFAULT_STATE)
        if action == "init":
            command.add_argument("--engine", required=True, help="Existing ComfyUI loopback URL")
            command.add_argument("--cloud-config", type=Path, help="Explicitly enable outbound account management")
        if action in {"serve", "start"}: command.add_argument("--port", type=int, default=0)
        if action == "add-recipe":
            command.add_argument("--id", required=True)
            command.add_argument("--title", required=True)
            command.add_argument("--workflow", type=Path, required=True, help="Owner-approved ComfyUI API-format JSON")


def running(path):
    try:
        value = json.loads((path / "running.json").read_text(encoding="utf-8"))
        from .comfyui import loopback_url
        loopback_url(value["origin"])
        if not isinstance(value["token"], str) or len(value["token"]) != 43: raise ValueError()
        return value
    except (OSError, ValueError, KeyError, TypeError): raise ValueError("runtime_not_running") from None


def request(path, method="GET", suffix="/api/status"):
    info = running(path)
    try:
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=5) as client:
            response = client.request(method, info["origin"]+suffix,
                                      headers={"Authorization": "Bearer "+info["token"], "Origin": info["origin"]})
        if response.status_code != 200: raise ValueError()
        return response.json()
    except (httpx.HTTPError, ValueError): raise ValueError("runtime_not_running") from None


def run(args):
    path = args.state.resolve()
    if args.runtime_action == "init": return initialize(path, args.engine, cloud_config=args.cloud_config)
    load(path)
    if args.runtime_action == "add-recipe":
        if args.workflow.stat().st_size > 1_000_000: raise ValueError("workflow_too_large")
        return RuntimeStore(path / "jobs.sqlite3").install_recipe(args.id, args.title,
                    json.loads(args.workflow.read_text(encoding="utf-8")))
    if args.runtime_action == "serve":
        from .runtime_server import serve
        serve(path, port=args.port)
        return {"stopped": True}
    if args.runtime_action == "start":
        try:
            request(path)
            return {"running": True, "origin": running(path)["origin"]}
        except ValueError: pass
        # Import before detaching so a missing optional dependency is actionable.
        from .runtime_server import serve
        options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS} if os.name == "nt" else {"start_new_session": True}
        with (path / "runtime.log").open("ab") as log:
            process = subprocess.Popen([sys.executable, "-m", "vgpu_local", "runtime", "serve", "--state", str(path),
                                        "--port", str(args.port)], stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       close_fds=True, **options)
        for _ in range(100):
            try:
                request(path)
                return {"running": True, "origin": running(path)["origin"]}
            except ValueError:
                if process.poll() is not None: raise ValueError("runtime_start_failed_check_local_log")
                time.sleep(.1)
        raise ValueError("runtime_start_unconfirmed_check_local_log")
    if args.runtime_action == "stop": return request(path, "POST", "/api/stop")
    if args.runtime_action == "open":
        request(path)
        info = running(path)
        webbrowser.open(info["origin"]+"/#"+info["token"])
        return {"opened": True, "origin": info["origin"]}
    return request(path)
