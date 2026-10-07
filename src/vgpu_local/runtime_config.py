"""Owner-local settings. Cloud keys remain in the OS keyring."""
import csv
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from .comfyui import loopback_url
from .runtime_store import RuntimeStore

DEFAULT_STATE = Path.home() / ".config/vgpu-local/runtime"


def private_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":
        result = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True,
                                text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        sid = next(csv.reader(result.stdout.strip().splitlines()))[1]
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                        f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                       check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        path.chmod(0o700)


def write_private(path, value, *, exclusive=False):
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as file:
        json.dump(value, file)
        file.flush()
        os.fsync(file.fileno())


def initialize(path, endpoint, *, cloud_config=None):
    path = path.resolve()
    if path.exists() and any(path.iterdir()): raise ValueError("runtime_directory_must_be_empty")
    settings = dict(version=1, installation_id="sit_"+uuid4().hex, engine_endpoint=loopback_url(endpoint))
    if cloud_config:
        from .cloud import CloudConnection, SystemKeyring
        cloud = CloudConnection(cloud_config.resolve(), SystemKeyring())
        enrolled = cloud.settings()
        settings.update(cloud_config=str(cloud_config.resolve()),
                        cloud_identity={k: enrolled[k] for k in ("endpoint", "tenant_id", "project_id", "site_id")})
    private_directory(path)
    RuntimeStore(path / "jobs.sqlite3", create=True)
    write_private(path / "config.json", settings, exclusive=True)
    return {"initialized": True, "state_directory": str(path), "mode": "connected" if cloud_config else "standalone"}


def load(path):
    try:
        settings = json.loads((path / "config.json").read_text(encoding="utf-8"))
        base = {"version", "installation_id", "engine_endpoint"}
        if set(settings) not in (base, base | {"cloud_config", "cloud_identity"}) or settings["version"] != 1:
            raise ValueError()
        import re
        if not re.fullmatch(r"sit_[a-f0-9]{32}", settings["installation_id"]): raise ValueError()
        loopback_url(settings["engine_endpoint"])
        return settings
    except (OSError, ValueError, TypeError, KeyError):
        raise ValueError("runtime_configuration_unavailable") from None
