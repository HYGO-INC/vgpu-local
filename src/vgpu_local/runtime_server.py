"""Optional same-origin console. Listener and bearer authentication are explicit."""
import asyncio
from contextlib import asynccontextmanager
import hmac
import json
from pathlib import Path
import secrets
import socket

from filelock import FileLock, Timeout
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
import uvicorn

from .comfyui import ComfyEngine
from .runtime import Runtime
from .runtime_config import load, write_private
from .runtime_store import RuntimeStore
from .errors import KeyConflict

ASSETS = Path(__file__).parent / "console"


class LocalBoundary:
    def __init__(self, app, *, origin, token):
        self.app, self.origin, self.token = app, origin, token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            return await self.app(scope, receive, send)
        request = Request(scope)
        origin = request.headers.get("origin")
        host = request.headers.get("host")
        forbidden = (host != self.origin.removeprefix("http://") or
                     (origin is not None and origin != self.origin) or
                     request.headers.get("sec-fetch-site") == "cross-site")
        if forbidden:
            return await JSONResponse({"error": "local_origin_required"}, 403)(scope, receive, send)
        if scope["path"].startswith("/api/"):
            supplied = request.headers.get("authorization", "")
            if not hmac.compare_digest(supplied.encode(), ("Bearer "+self.token).encode()):
                return await JSONResponse({"error": "local_session_required"}, 401)(scope, receive, send)
        # Bound streaming bodies before any parser. No file upload or workflow API.
        size = 0
        async def bounded():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > 32768: raise ValueError("request_too_large")
            return message
        async def secured(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend([
                    (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"content-security-policy", b"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"),
                ])
            await send(message)
        await self.app(scope, bounded, secured)


def application(runtime, installation_id, *, origin, token, shutdown):
    def view(job):
        return {**runtime.store.report(job), "outputs": job["outputs"]}

    async def status(request):
        return JSONResponse({"mode": "connected" if runtime.cloud else "standalone", "cloud": runtime.cloud_state,
                             "recipes": runtime.store.recipes(), "jobs": [view(j) for j in runtime.store.jobs()]})

    async def job(request):
        try: return JSONResponse(view(runtime.store.job(request.path_params["id"])))
        except ValueError: return JSONResponse({"error": "execution_not_found"}, 404)

    async def command(request):
        try:
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse({"error": "json_required"}, 415)
            body = await request.json()
            if set(body) != {"command"}: raise ValueError("invalid_command")
            document = body["command"]
            scope = {"tenant_id": "local", "project_id": "local", "site_id": installation_id}
            # The local owner may also cancel a cloud-managed job. It cannot start
            # one under a forged cloud scope through the console.
            if document.get("action") == "cancel": scope = runtime.store.job(document["execution_id"])["scope"]
            receipt = runtime.store.accept(document, scope, origin="local")
            return JSONResponse(receipt, 202 if receipt["accepted"] else 409)
        except (ValueError, TypeError, KeyError, KeyConflict):
            return JSONResponse({"error": "invalid_or_conflicting_command"}, 400)

    async def prepare(request):
        # Mint one command per explicit click; the browser retains and retries
        # the SAME command if POST /commands loses its response.
        try:
            body = await request.json()
            if set(body) - {"action", "recipe_id", "execution_id"}: raise ValueError()
            document = runtime.store.local_command(installation_id, body["action"], body.get("recipe_id"),
                                                   execution_id=body.get("execution_id"))
            return JSONResponse(document)
        except (ValueError, KeyError, TypeError): return JSONResponse({"error": "invalid_command"}, 400)

    async def stop(request):
        shutdown()
        return JSONResponse({"stopping": True, "engine_jobs_canceled": False})

    async def asset(request):
        name = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}[request.url.path]
        media = {"index.html": "text/html", "app.js": "text/javascript", "style.css": "text/css"}[name]
        return Response((ASSETS / name).read_bytes(), media_type=media)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(runtime.run())
        # Fatal local storage errors stop serving instead of showing a healthy agent.
        task.add_done_callback(lambda done: shutdown() if not runtime.stopping.is_set() else None)
        yield
        runtime.stopping.set()
        await task

    app = Starlette(routes=[Route(path, asset) for path in ("/", "/app.js", "/style.css")]+[
        Route("/api/status", status), Route("/api/jobs/{id}", job),
        Route("/api/commands/prepare", prepare, methods=["POST"]),
        Route("/api/commands", command, methods=["POST"]), Route("/api/stop", stop, methods=["POST"]),
    ], lifespan=lifespan)
    return LocalBoundary(app, origin=origin, token=token)


def serve(path, *, port=0):
    settings = load(path)
    lock = FileLock(path / "runtime.lock", timeout=0)
    try: lock.acquire()
    except Timeout: raise ValueError("runtime_already_running") from None
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        listener.bind(("127.0.0.1", port))
        listener.listen(128)
        store = RuntimeStore(path / "jobs.sqlite3")
        cloud = None
        if "cloud_config" in settings:
            from .cloud import CloudConnection, SystemKeyring
            cloud = CloudConnection(Path(settings["cloud_config"]), SystemKeyring())
        runtime = Runtime(store, ComfyEngine(settings["engine_endpoint"]), cloud=cloud,
                          cloud_identity=settings.get("cloud_identity"))
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        token = secrets.token_urlsafe(32)
        server = None
        app = application(runtime, settings["installation_id"], origin=origin, token=token,
                          shutdown=lambda: setattr(server, "should_exit", True))
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=listener.getsockname()[1],
                                access_log=False, log_level="warning", proxy_headers=False, ws="none"))
        write_private(path / "running.json", {"origin": origin, "token": token})
        server.run(sockets=[listener])
    finally:
        listener.close()
        (path / "running.json").unlink(missing_ok=True)
        lock.release()
