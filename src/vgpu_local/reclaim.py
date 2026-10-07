"""Trusted local reclaim glue, using the existing controller and backend owners.

This is a single reconciliation step, not a scheduler. A hosted installation uses
its lifecycle owner instead; never run two competing reclaim owners for a lease.
"""
from typing import Protocol

from .contracts.models import BackendObservation, BackendRequest
from .errors import OutcomeUnknown
from .interruptions import InterruptionConflict, InterruptionController
from .journal import fingerprint


class ReclaimBackend(Protocol):
    def observe(self, request: BackendRequest) -> BackendObservation: ...
    def release(self, request: BackendRequest) -> BackendObservation: ...


class LocalReclaimer:
    def __init__(self, controller: InterruptionController, backend: ReclaimBackend,
                 request: BackendRequest, resource_id: str):
        self.request = BackendRequest.model_validate(request.model_dump())
        if (request.provider not in {"kubernetes", "simulator"} or request.workload_trust != "owner"
                or any(getattr(request, key) != getattr(controller.scope, key)
                       for key in ("tenant_id", "project_id", "generation"))):
            raise ValueError("local owner reclaim must match the runtime scope and backend")
        if not isinstance(resource_id, str) or not 1 <= len(resource_id) <= 255:
            raise ValueError("bind a previously observed resource identity")
        self.controller, self.backend, self.resource_id = controller, backend, resource_id
        self.key = fingerprint({"local_reclaim":controller.key})
        self.store = controller.store
        self.store.begin(self.key, {"request":self.request.model_dump(mode="json"),"resource_id":resource_id},
                         {"authorized":False,"observation":None,"completed":False})

    def step(self, now_ms: int) -> dict:
        if type(now_ms) is not int or not 0 <= now_ms <= 9007199254740991:
            raise ValueError("trusted current time must be nonnegative integer milliseconds")
        row = self.store.read(self.key)
        if row["completed"]:
            return self._result(row)
        snapshot = self.controller.snapshot()
        if not row["authorized"]:
            # Authorization commits in the notice journal before any backend call.
            # A crash between these two receipts is recovered from phase=releasing.
            approved = any(item.phase == "releasing" for item in snapshot.interruptions)
            if not approved:
                for item in sorted(snapshot.interruptions, key=lambda item:
                                   (item.signal_at_ms if item.signal_at_ms is not None else
                                    item.release_by_ms if item.release_by_ms is not None else 9007199254740992,
                                    item.interruption_id)):
                    if item.phase != "scheduled" or item.source.kind == "advisory":
                        continue
                    try:
                        self.controller.authorize_release(item.interruption_id, item.version, now_ms)
                        approved = True
                        break
                    except InterruptionConflict:
                        # Not ready/due, or a concurrent withdrawal/extension won.
                        # A future step reads the new version; do not invent intent.
                        continue
            if not approved:
                return {"state":"waiting","cursor":self.controller.snapshot().cursor}
            row = self.store.change(self.key, lambda current: {**current,"authorized":True})

        if not self._released(row["observation"]):
            # Bind the live observed resource before requesting any teardown.
            # Unknown/missing/mismatched observations cannot authorize a delete.
            observed = self._verify(self.backend.observe(self.request))
            row = self._remember(observed)
            if not self._released(row["observation"]):
                if observed.state == "unknown" or observed.supplier_state == "unknown":
                    raise OutcomeUnknown("reclaim requires a current identified resource")
                row = self._remember(self._verify(self.backend.release(self.request)))

        if self._released(row["observation"]):
            # The backend evidence is durable before closing the notice. A later
            # caller can finish publication without repeating the supplier action.
            evidence = "backend-" + fingerprint(row["observation"])
            snapshot = self.controller.snapshot()
            releasing = next((item for item in snapshot.interruptions if item.phase == "releasing"), None)
            if releasing is not None:
                try:
                    self.controller.confirm_released(releasing.interruption_id, releasing.version,
                                                     backend_evidence_id=evidence)
                except InterruptionConflict:
                    return {"state":"confirming","cursor":self.controller.snapshot().cursor}
            elif any(item.phase == "scheduled" for item in snapshot.interruptions):
                raise InterruptionConflict("authorized reclaim lost its notice evidence")
            row = self.store.change(self.key, lambda current: {**current,"completed":True})
        return self._result(row)

    def _verify(self, observation):
        value = BackendObservation.model_validate(observation.model_dump())
        if (value.resource_id != self.resource_id or any(getattr(value,key) != getattr(self.request,key)
                for key in ("tenant_id","project_id","provider","account_id","operation_id","generation"))):
            raise OutcomeUnknown("backend observation does not identify the bound reclaim resource")
        return value

    def _remember(self, observation):
        value = observation.model_dump(mode="json")
        def update(row):
            old = row["observation"]
            if old is not None:
                if self._released(old): return row
                if value["revision"] < old["revision"]:
                    raise OutcomeUnknown("late backend observation cannot advance reclaim")
                if value["revision"] == old["revision"] and value != old:
                    raise OutcomeUnknown("backend revision was reused with changed evidence")
                if old["state"] in {"lost","released"} and value["state"] not in {old["state"],"released"}:
                    raise OutcomeUnknown("terminal backend evidence cannot be resurrected")
            return {**row,"observation":value}
        return self.store.change(self.key, update)

    @staticmethod
    def _released(observation):
        return observation is not None and observation["supplier_state"] == "released" and observation["state"] in {"released","lost"}

    def _result(self, row):
        return {"state":"completed" if row["completed"] else "releasing",
                "cursor":self.controller.snapshot().cursor,"observation":row["observation"]}
