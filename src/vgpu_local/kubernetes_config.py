"""Shared operator site configuration; contains no customer-selected credentials."""
import json

from .kubernetes import render_job


def validate_config(config: dict) -> dict:
    required = {"context", "namespace", "namespace_uid", "queue", "region", "gpu_classes"}
    optional = {"kubeconfig", "runtime_class", "queue_api_version"}
    if not isinstance(config, dict) or not required <= set(config) or set(config) - required - optional:
        raise ValueError("Kubernetes configuration requires explicit site and GPU bindings")
    result = {"runtime_class": "nvidia", "queue_api_version": "v1beta1", **config}
    for key, value in result.items():
        if key != "gpu_classes" and (not isinstance(value, str) or not value or len(value) > 1024):
            raise ValueError("Kubernetes configuration strings must be nonempty and bounded")
    if result["queue_api_version"] not in {"v1beta1", "v1beta2"}:
        raise ValueError("Unsupported Kueue API version")
    classes = result["gpu_classes"]
    if not isinstance(classes, dict) or not 1 <= len(classes) <= 128:
        raise ValueError("Configure 1..128 GPU classes")
    for name, gpu in classes.items():
        if (not isinstance(name, str) or not 1 <= len(name) <= 128 or not isinstance(gpu, dict)
                or set(gpu) != {"resource", "product"} or any(not isinstance(v, str) for v in gpu.values())):
            raise ValueError("Each named GPU class requires resource and product strings")
        render_job(name="validate", namespace=result["namespace"], queue=result["queue"],
                   runtime_class=result["runtime_class"], image="validate:1", command=["true"],
                   gpu_resource=gpu["resource"], gpu_product=gpu["product"])
    if len(json.dumps(result).encode()) > 65_536:
        raise ValueError("Kubernetes configuration exceeds 64 KiB")
    return json.loads(json.dumps(result))
