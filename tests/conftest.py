import pytest

from vgpu_local.contracts.models import BackendRequest


@pytest.fixture
def request_data():
    return dict(tenant_id="tenant-a", project_id="project-a", account_id="account-a",
                operation_id="create-a", generation=1, provider="simulator",
                image="example/workload@sha256:" + "a" * 64, gpu_model="RTX4090",
                gpu_count=1, num_nodes=1, region="region-a", capacity_mode="on_demand",
                workload_trust="owner", max_hourly_price_microusd=500000, command=["python", "train.py"])


@pytest.fixture
def backend_request(request_data):
    return BackendRequest.model_validate(request_data)
