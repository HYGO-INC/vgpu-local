"""Vast/Runpod integration through SkyPilot; no second direct provisioner."""
from decimal import Decimal
import importlib.metadata
import shlex
from collections.abc import Mapping

from .contracts.models import BackendObservation, BackendRequest
from .errors import OutcomeUnknown, UnsupportedCapability
from .journal import ReceiptStore, scope


def task_config(request: BackendRequest) -> dict:
    if not request.command[0]:
        raise ValueError("command executable must be nonempty")
    if request.provider not in {"vast", "runpod"}:
        raise UnsupportedCapability("this adapter handles Vast and Runpod")
    if request.num_nodes != 1:
        raise UnsupportedCapability("multi-node is not qualified in these SkyPilot provider paths")
    if request.workload_trust != "owner":
        raise UnsupportedCapability("supplier credential isolation is not qualified for untrusted workloads")
    return {
        "name": "vgpu-workload", "num_nodes": 1,
        "resources": {
            "cloud": request.provider,
            "accelerators": {request.gpu_model: request.gpu_count},
            "region": request.region,
            "image_id": "docker:" + request.image,
            "use_spot": request.capacity_mode == "spot",
            "max_hourly_cost": float(Decimal(request.max_hourly_price_microusd) / 1_000_000),
        },
        "run": shlex.join(request.command),
    }


class SkyPilotBackend:
    def __init__(self, journal: ReceiptStore, sdk=None, *, account_id: str | None = None):
        if sdk is None:
            if not account_id:
                raise UnsupportedCapability("bind the SkyPilot worker to an explicitly configured provider account")
            if importlib.metadata.version("skypilot") != "0.14.0":
                raise UnsupportedCapability("use the reviewed SkyPilot 0.14.0 worker environment")
            import sky
            sdk = sky
        self.sdk, self.journal = sdk, journal
        self.account_id = account_id

    def _account(self, request):
        if self.account_id is not None and request.account_id != self.account_id:
            raise UnsupportedCapability("request does not belong to this SkyPilot account worker")

    def provision(self, request: BackendRequest) -> dict:
        self._account(request)
        config = task_config(request)  # validate before reserving an operation or contacting a supplier
        task = self.sdk.Task.from_yaml_config(config)
        key = scope(request)
        created, receipt = self.journal.begin(key, request.model_dump(), {
            "state": "uncertain", "cluster_name": "vg" + key[:20],
        })
        if not created:
            if receipt["state"] in {"ready", "released"}:
                return receipt
            raise OutcomeUnknown("existing SkyPilot operation needs reconciliation")
        try:
            request_id = self.sdk.launch(task, cluster_name=receipt["cluster_name"], retry_until_up=False)
            self.journal.change(key, lambda row: {**row, "request_id": str(request_id)})
            self.sdk.get(request_id)
        except Exception as exc:
            raise OutcomeUnknown("SkyPilot create may have succeeded; reconcile the recorded request") from exc
        return self.journal.transition(key, "uncertain", "ready")[1]

    def reconcile(self, request: BackendRequest) -> dict:
        receipt = self._owned(request)
        if receipt["state"] in {"ready", "released"}:
            return receipt
        if receipt["state"] != "uncertain" or "request_id" not in receipt:
            raise OutcomeUnknown("requires supplier inventory reconciliation; absence from SkyPilot is insufficient")
        try:
            self.sdk.get(receipt["request_id"])
        except Exception as exc:
            raise OutcomeUnknown("recorded SkyPilot operation remains unresolved") from exc
        return self.journal.transition(scope(request), "uncertain", "ready")[1]

    def _owned(self, request: BackendRequest) -> dict:
        self._account(request)
        # begin also verifies the complete request fingerprint; no implicit adoption.
        self.journal.read(scope(request))
        _, receipt = self.journal.begin(scope(request), request.model_dump(), {})
        return receipt

    def observe(self, request: BackendRequest) -> BackendObservation:
        """Fresh capacity status, not cached launch success or workload completion.

        SkyPilot omits both terminated and unknown clusters. Such absence cannot
        prove provider teardown and must never authorize another create.
        """
        receipt = self._owned(request)
        key = scope(request)
        ticket = self.journal.change(key, lambda row: {**row, "observation_poll": row.get("observation_poll", 0) + 1})["observation_poll"]
        state, supplier = "unknown", "unknown"
        if receipt["state"] == "released":
            state, supplier = "released", "released"
        elif receipt["state"] == "ready":
            try:
                # The pinned request model parses this StatusRefreshMode value.
                # Its docstring's old refresh=True example no longer validates.
                response = self.sdk.status(cluster_names=[receipt["cluster_name"]], refresh="FORCE", all_users=False,
                                           _include_credentials=False)
                records = self.sdk.get(response)
                if not isinstance(records, list) or len(records) > 1:
                    raise ValueError("ambiguous cluster status")
                if records:
                    record = records[0]
                    if not isinstance(record, Mapping) or record.get("name") != receipt["cluster_name"]:
                        raise ValueError("cluster status identity mismatch")
                    status = record.get("status")
                    status = status.value if hasattr(status, "value") else status
                    if status == "UP": state, supplier = "running", "allocated"
                    elif status == "STOPPED": state, supplier = "paused", "allocated"
                    elif status != "INIT": raise ValueError("unknown SkyPilot status")
            except Exception as exc:
                self._observation(request, ticket, "unknown", "unknown")
                raise OutcomeUnknown("fresh SkyPilot status is unavailable or unverified") from exc
        return self._observation(request, ticket, state, supplier)

    def _observation(self, request, ticket, state, supplier):
        def update(row):
            previous = row.get("observation")
            if previous and ticket <= row.get("observation_applied_poll", 0): return row
            # A concurrent completed teardown dominates an earlier status reply.
            effective_state, effective_supplier = (state, supplier) if row["state"] == "ready" else ("unknown", "unknown")
            if row["state"] == "released": effective_state, effective_supplier = "released", "released"
            observation = {key: getattr(request, key) for key in (
                "tenant_id", "project_id", "account_id", "operation_id", "provider", "generation")}
            observation.update(resource_id=row["cluster_name"], state=effective_state, supplier_state=effective_supplier,
                               revision=previous["revision"] if previous else 1)
            if previous and observation != previous: observation["revision"] += 1
            row.update(observation=BackendObservation.model_validate(observation).model_dump(), observation_applied_poll=ticket)
            return row
        return BackendObservation.model_validate(self.journal.change(scope(request), update)["observation"])

    def release(self, request: BackendRequest) -> dict:
        receipt = self._owned(request)
        if receipt["state"] == "released":
            return receipt
        if receipt["state"] != "ready":
            raise OutcomeUnknown("reconcile creation/cleanup before releasing")
        claimed, receipt = self.journal.transition(scope(request), "ready", "release_pending")
        if not claimed:
            if receipt["state"] == "released":
                return receipt
            raise OutcomeUnknown("cleanup is already owned by another caller")
        try:
            request_id = self.sdk.down(receipt["cluster_name"], purge=False)
            self.journal.change(scope(request), lambda row: {**row, "release_request_id": str(request_id)})
            self.sdk.get(request_id)
        except Exception as exc:
            raise OutcomeUnknown("supplier cleanup remains pending") from exc
        return self.journal.transition(scope(request), "release_pending", "released")[1]

    def reconcile_release(self, request: BackendRequest) -> dict:
        receipt = self._owned(request)
        if receipt["state"] == "released":
            return receipt
        if receipt["state"] != "release_pending" or "release_request_id" not in receipt:
            raise OutcomeUnknown("cleanup needs supplier inventory reconciliation")
        try:
            self.sdk.get(receipt["release_request_id"])
        except Exception as exc:
            raise OutcomeUnknown("supplier cleanup remains pending") from exc
        return self.journal.transition(scope(request), "release_pending", "released")[1]
