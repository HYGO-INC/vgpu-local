import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_offline_inventory_cli():
    result = subprocess.run(["vgpu-local", "inventory", "--nodes-json", "examples/nodes.json"],
                            cwd=ROOT, capture_output=True, text=True, check=True)
    rows = json.loads(result.stdout)
    assert len(rows) == 3
    assert rows[1]["gpu_product"] == "NVIDIA-GeForce-RTX-5090"


def test_renderer_does_not_execute_command(tmp_path):
    target = tmp_path / "must-not-exist"
    result = subprocess.run(["vgpu-local", "render-job", "--name", "test", "--image", "example:1",
                             "--", "touch", str(target)], cwd=ROOT, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["spec"]["suspend"] is True
    assert not target.exists()


def test_multi_gpu_job_is_single_node_in_rendering_and_discovery():
    result = subprocess.run(["vgpu-local", "render-job", "--name", "two-gpus",
                             "--image", "example:1", "--gpus", "2", "--", "nvidia-smi"],
                            cwd=ROOT, capture_output=True, text=True, check=True)
    job = json.loads(result.stdout)
    assert job["apiVersion"] == "batch/v1"
    assert job["kind"] == "Job"
    assert job["spec"].get("parallelism", 1) == 1
    assert job["spec"].get("completions", 1) == 1
    resources = job["spec"]["template"]["spec"]["containers"][0]["resources"]
    assert resources["requests"] == resources["limits"] == {"nvidia.com/gpu": 2}

    profile = subprocess.run(["vgpu-local", "capabilities", "kubernetes"],
                             cwd=ROOT, capture_output=True, text=True, check=True)
    assert json.loads(profile.stdout)["supports_multi_node"] is False
