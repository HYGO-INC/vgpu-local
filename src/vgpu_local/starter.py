"""Dependency-free discovery. Never installs software or launches a workload."""
import csv
import http.client
import io
import json
import platform
import shutil
import subprocess
import sys
from urllib.parse import urlsplit


def register(commands):
    doctor = commands.add_parser("doctor", help="Inspect this computer without downloads or a cluster")
    doctor.add_argument("--no-probe", action="store_true", help="Do not invoke nvidia-smi")
    engine = commands.add_parser("engine", help="Inspect an already installed local engine")
    sub = engine.add_subparsers(dest="engine_action", required=True)
    status = sub.add_parser("status")
    status.add_argument("--kind", choices=["comfyui", "ollama", "vllm"], required=True)
    status.add_argument("--endpoint", required=True, help="Explicit loopback HTTP URL, including port")


def gpu_rows(output: str) -> list[dict]:
    if len(output) > 65536:
        raise ValueError("gpu_inventory_too_large")
    rows = []
    for row in csv.reader(io.StringIO(output), skipinitialspace=True):
        if not row:
            continue
        if len(row) != 4 or not row[0].startswith("GPU-"):
            raise ValueError("invalid_gpu_inventory")
        total, free = int(row[2]), int(row[3])
        if total <= 0 or not 0 <= free <= total:
            raise ValueError("invalid_gpu_memory")
        rows.append(dict(uuid=row[0], name=row[1], memory_total_mib=total, memory_free_mib=free))
    return rows


def doctor(*, probe=True):
    path = shutil.which("nvidia-smi")
    result = {
        "mode": "local", "python": platform.python_version(), "platform": sys.platform,
        "gpus": [], "gpu_probe": "not_requested" if not probe else "nvidia_smi_unavailable",
        "tools": {tool: shutil.which(tool) is not None for tool in ("nvidia-smi", "ollama", "docker", "kubectl")},
        "required_services": [], "account_required": False, "kubernetes_required": False,
        "downloads_started": False,
        "memory_meaning": "per-device snapshot; neither a reservation nor combined VRAM",
    }
    if path and probe:
        try:
            output = subprocess.run([path, "--query-gpu=uuid,name,memory.total,memory.free",
                                     "--format=csv,noheader,nounits"],
                                    capture_output=True, text=True, timeout=10, check=True)
            result["gpus"] = gpu_rows(output.stdout)
            result["gpu_probe"] = "available"
        except (OSError, ValueError, subprocess.SubprocessError):
            result["gpu_probe"] = "failed"
    return result


def engine_status(kind: str, endpoint: str):
    paths = {"comfyui": "/system_stats", "ollama": "/api/tags", "vllm": "/v1/models"}
    if kind not in paths:
        raise ValueError("unsupported_local_engine")
    try:
        url = urlsplit(endpoint)
        if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1"}
                or not url.port or url.username is not None or url.password is not None
                or url.path not in {"", "/"} or url.query or url.fragment):
            raise ValueError()
    except ValueError:
        raise ValueError("explicit_loopback_http_endpoint_required") from None
    # No DNS names, proxies, redirects, automatic discovery or model pull routes.
    client = http.client.HTTPConnection(url.hostname, url.port, timeout=5)
    try:
        client.request("GET", paths[kind], headers={"Accept": "application/json"})
        response = client.getresponse()
        if response.status != 200:
            raise RuntimeError("local_engine_status_unavailable")
        body = response.read(65537)
        if len(body) > 65536:
            raise ValueError("local_engine_response_too_large")
        payload = json.loads(body)
        field = {"comfyui": "devices", "ollama": "models", "vllm": "data"}[kind]
        if not isinstance(payload, dict) or not isinstance(payload.get(field), list):
            raise ValueError("unexpected_local_engine_response")
        return {"kind": kind, "reachable": True, "endpoint": endpoint.rstrip("/"),
                "reported_entries": len(payload[field]), "downloads_started": False,
                "meaning": "API shape recognized; inference and GPU allocation not qualified"}
    except (OSError, http.client.HTTPException, json.JSONDecodeError):
        raise RuntimeError("local_engine_status_unavailable") from None
    finally:
        client.close()


def run(args):
    if args.action == "doctor":
        return doctor(probe=not args.no_probe)
    return engine_status(args.kind, args.endpoint)
