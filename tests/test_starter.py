import http.server
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from vgpu_local.starter import doctor, engine_status, gpu_rows


def test_starter_runs_with_site_packages_disabled():
    # -S removes *all* installed third-party packages. This catches accidental
    # optional imports in the CLI, not only its dependency declarations.
    root = Path(__file__).resolve().parents[1]
    code = "import sys; sys.path.insert(0, 'src'); from vgpu_local.cli import main; main()"
    process = subprocess.run([sys.executable, "-S", "-c", code, "doctor", "--no-probe"],
                             cwd=root, capture_output=True, text=True, check=True)
    status = json.loads(process.stdout)
    assert status["downloads_started"] is False
    assert status["account_required"] is False
    assert status["kubernetes_required"] is False
    assert status["required_services"] == []
    for command in ("cloud", "kubernetes", "interruption"):
        args = [command, "status"] if command == "cloud" else [command, "--help"]
        result = subprocess.run([sys.executable, "-S", "-c", code, *args],
                                cwd=root, capture_output=True, text=True)
        assert result.returncode == 2
        assert "optional vgpu-local[" in result.stderr
        assert "Traceback" not in result.stderr


def test_doctor_never_installs_and_keeps_separate_gpu_memory(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "nvidia-smi" if name == "nvidia-smi" else None)
    calls = []
    def inspect(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, 'GPU-a, RTX 4090, 24564, 20000\nGPU-b, RTX 5090, 32768, 30000\n')
    monkeypatch.setattr("subprocess.run", inspect)
    state = doctor()
    assert len(calls) == 1 and "--query-gpu=" in calls[0][1]
    assert [gpu["memory_total_mib"] for gpu in state["gpus"]] == [24564, 32768]
    assert not state["tools"]["kubectl"]
    assert not doctor(probe=False)["gpus"] and len(calls) == 1


@pytest.mark.parametrize("row", ["oops", "GPU-a,Name,-1,0", "GPU-a,Name,24,25", "x" * 65537],
                         ids=["malformed", "negative", "overfull", "oversized"])
def test_bad_inventory_is_not_reported_as_capacity(row):
    with pytest.raises(ValueError): gpu_rows(row)


@pytest.mark.parametrize("endpoint", ["http://localhost:8188", "https://127.0.0.1:8188",
    "http://example.com:8188", "http://127.0.0.1", "http://127.0.0.1:0",
    "http://user@127.0.0.1:8188", "http://127.0.0.1:8188/?token=x",
    "http://127.0.0.1:8188/api", "http://127.0.0.1:8188/#x"])
def test_engine_probe_rejects_nonlocal_or_credential_urls(endpoint):
    with pytest.raises(ValueError, match="explicit_loopback"):
        engine_status("comfyui", endpoint)


def test_real_loopback_http_requests_are_read_only_and_bounded():
    paths = []
    response = {"code": 200, "body": b'{"devices":[]}', "headers": {}}
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(response["code"])
            for key, value in response["headers"].items(): self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response["body"])
        def log_message(self, *args): pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    try:
        for kind, field, path in [("comfyui", "devices", "/system_stats"),
                                  ("ollama", "models", "/api/tags"), ("vllm", "data", "/v1/models")]:
            response["body"] = json.dumps({field: [dict(name="local")]}).encode()
            result = engine_status(kind, endpoint)
            assert result["reported_entries"] == 1 and not result["downloads_started"]
            assert paths[-1] == path
        response.update(code=302, headers={"Location": "http://must-not-be-contacted.invalid"})
        with pytest.raises(RuntimeError, match="unavailable"): engine_status("comfyui", endpoint)
        assert len(paths) == 4
        response.update(code=200, headers={}, body=b"x" * 65537)
        with pytest.raises(ValueError, match="too_large"): engine_status("comfyui", endpoint)
        response["body"] = b'{}'
        with pytest.raises(ValueError, match="unexpected"): engine_status("comfyui", endpoint)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
