"""Native Kueue jobs and inventory. Kubernetes remains the scheduler."""
import re

from .journal import fingerprint


def gpu_inventory(nodes: dict) -> list[dict]:
    inventory = []
    for node in nodes.get("items", []):
        metadata, status = node.get("metadata", {}), node.get("status", {})
        resources = {name: count for name, count in status.get("allocatable", {}).items()
                     if name == "nvidia.com/gpu" or name.startswith("nvidia.com/mig-")}
        if not resources:
            continue
        labels = metadata.get("labels", {})
        inventory.append({
            "name": metadata["name"], "allocatable": resources,
            "gpu_product": labels.get("nvidia.com/gpu.product", "unknown"),
            "ready": any(c.get("type") == "Ready" and c.get("status") == "True" for c in status.get("conditions", [])),
            "unschedulable": node.get("spec", {}).get("unschedulable", False),
            "taints": node.get("spec", {}).get("taints", []),
            "capacity_meaning": "scheduler allocatable, not current free capacity",
        })
    return inventory


def render_job(*, name: str, namespace: str, queue: str, image: str, command: list[str],
               gpu_count: int = 1, gpu_resource: str = "nvidia.com/gpu", runtime_class: str = "nvidia",
               gpu_product: str | None = None) -> dict:
    for value in (name, namespace, queue, runtime_class):
        if not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", value):
            raise ValueError("names must be DNS labels of at most 63 characters")
    if type(gpu_count) is not int or not 1 <= gpu_count <= 1024:
        raise ValueError("GPU count must be a positive integer")
    if not re.fullmatch(r"nvidia\.com/(gpu|mig-[a-zA-Z0-9.-]+)", gpu_resource):
        raise ValueError("use a whole-device or discovered MIG resource name")
    if not image or not command or any(not isinstance(arg, str) or not arg for arg in command):
        raise ValueError("image and command arguments are required")
    if gpu_product is not None and (not isinstance(gpu_product, str) or not gpu_product):
        raise ValueError("GPU product selector must be a nonempty string")
    pod = {
        "restartPolicy": "Never", "runtimeClassName": runtime_class,
        "automountServiceAccountToken": False,
        "containers": [{"name": "workload", "image": image, "command": command,
                        "resources": {"requests": {gpu_resource: gpu_count}, "limits": {gpu_resource: gpu_count}}}],
    }
    if gpu_product is not None:
        pod["nodeSelector"] = {"nvidia.com/gpu.product": gpu_product}
    spec = {"suspend": True, "backoffLimit": 0, "template": {"spec": pod}}
    return {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": name, "namespace": namespace,
                     "labels": {"kueue.x-k8s.io/queue-name": queue, "app.kubernetes.io/managed-by": "vgpu-local"},
                     "annotations": {"vgpu.com/spec-sha256": fingerprint(spec)}},
        "spec": spec,
    }
