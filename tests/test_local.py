from dataclasses import replace

import pytest

from vgpu_local.contracts.models import BurstPolicy
from vgpu_local.kubernetes import gpu_inventory, render_job
from vgpu_local.overflow import OverflowContext, overflow_denials


def policy(**overrides):
    return BurstPolicy(mode="automatic", allowed_providers=["vast"], allowed_regions=["region-a"],
                       max_hourly_price_microusd=500000, max_total_spend_microusd=10000000,
                       max_concurrent_remote_jobs=2, local_wait_seconds=60,
                       data_policy="artifacts_only", **overrides)


def context():
    return OverflowContext("fenced", 60, "vast", "region-a", 250000, 1000000, 0, 0, True)


def test_overflow_default_is_off():
    disabled = BurstPolicy(mode="disabled", allowed_providers=[], allowed_regions=[],
                           max_hourly_price_microusd=0, max_total_spend_microusd=0,
                           max_concurrent_remote_jobs=0, local_wait_seconds=0, data_policy="local_only")
    assert overflow_denials(disabled, context()) == ["cloud_disabled"]
    assert overflow_denials(policy(), context()) == []


@pytest.mark.parametrize("override,reason", [
    ({"local_state": "queued"}, "local_execution_not_fenced"),
    ({"local_state": "running"}, "local_execution_not_fenced"),
    ({"local_state": "unknown"}, "local_execution_not_fenced"),
    ({"provider": "runpod"}, "provider_not_allowed"),
    ({"region": "other-region"}, "region_not_allowed"),
    ({"hourly_price_microusd": 500001}, "hourly_price_limit"),
    ({"reservation_microusd": 10000001}, "spending_limit"),
    ({"spent_and_reserved_microusd": 10000000}, "spending_limit"),
    ({"active_remote_jobs": 2}, "remote_concurrency_limit"),
    ({"artifacts_ready": False}, "data_export_not_ready"),
    ({"waited_seconds": 59}, "local_wait_threshold"),
    ({"reservation_microusd": True}, "invalid_observation"),
])
def test_overflow_restrictions(override, reason):
    assert reason in overflow_denials(policy(), replace(context(), **override))


def test_manual_and_local_data_policies():
    manual = BurstPolicy.model_validate({**policy().model_dump(), "mode": "manual"})
    assert overflow_denials(manual, context()) == ["manual_request_required"]
    assert overflow_denials(manual, replace(context(), manually_requested=True)) == []
    private = BurstPolicy.model_validate({**policy().model_dump(), "data_policy": "local_only"})
    assert "data_export_not_ready" in overflow_denials(private, context())


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
