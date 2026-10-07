import pytest
from vgpu_local.kubernetes import gpu_inventory, render_job

@pytest.mark.parametrize("resource", ["nvidia.com/gpu", "nvidia.com/mig-1g.10gb"])
def test_native_kueue_admission_and_gpu_resource(resource):
    job = render_job(name="training", namespace="vgpu-local", queue="local-gpu",
                     image="example/workload:1", command=["python", "train.py"], gpu_resource=resource)
    assert job["spec"]["suspend"] is True
    assert job["spec"]["backoffLimit"] == 0
    pod = job["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["containers"][0]["resources"]["limits"] == {resource: 1}
    assert job["metadata"]["labels"]["kueue.x-k8s.io/queue-name"] == "local-gpu"


def test_inventory_is_allocatable_not_free_or_merged_memory():
    inventory = gpu_inventory({"items": [{
        "metadata": {"name": "home", "labels": {"nvidia.com/gpu.product": "NVIDIA-GeForce-RTX-5090"}},
        "status": {"allocatable": {"nvidia.com/gpu": "2", "cpu": "24"},
                   "conditions": [{"type": "Ready", "status": "True"}]},
    }]})
    assert inventory[0]["allocatable"] == {"nvidia.com/gpu": "2"}
    assert "not current free capacity" in inventory[0]["capacity_meaning"]


@pytest.mark.parametrize("name", ["../oops", "bad name", "x" * 64])
def test_invalid_job_names(name):
    with pytest.raises(ValueError):
        render_job(name=name, namespace="local", queue="gpu", image="image", command=["true"])
