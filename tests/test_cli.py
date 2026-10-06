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
