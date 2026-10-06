"""Deterministic, persistent fault simulator. Never creates a real GPU resource."""
from dataclasses import dataclass

from .contracts.models import BackendObservation, BackendRequest
from .errors import OutcomeUnknown
from .journal import Journal, scope


@dataclass(frozen=True)
class Faults:
    lose_create_reply: bool = False
    fail_teardown: bool = False


class Simulator:
    def __init__(self, journal: Journal, faults: Faults = Faults()):
        self.journal, self.faults = journal, faults

    def provision(self, request: BackendRequest) -> BackendObservation:
        if request.provider != "simulator":
            raise ValueError("simulator requests must identify the simulator")
        key = scope(request)
        initial = {key: getattr(request, key) for key in (
            "tenant_id", "project_id", "account_id", "operation_id", "provider", "generation")}
        observation = BackendObservation(**initial, resource_id="sim-" + key[:20], revision=1,
                                         state="running", supplier_state="allocated")
        created, row = self.journal.begin(key, request.model_dump(), {
            "observation": observation.model_dump(), "previous": observation.model_dump(),
            "clock": 0, "events": [], "event_sequence": 0,
        })
        if created and self.faults.lose_create_reply:
            raise OutcomeUnknown("simulated lost create response")
        return BackendObservation.model_validate(row["observation"])

    def observe(self, request: BackendRequest, *, stale: bool = False) -> BackendObservation:
        row = self._owned(request)
        return BackendObservation.model_validate(row["previous" if stale else "observation"])

    def _owned(self, request):
        self.journal.read(scope(request))
        _, row = self.journal.begin(scope(request), request.model_dump(), {})
        return row

    @staticmethod
    def _event(row: dict, kind: str, **details):
        row["event_sequence"] += 1
        row["events"].append({"id": str(row["event_sequence"]), "kind": kind, **details})

    @staticmethod
    def _transition(row: dict, state: str, supplier_state: str):
        row["previous"] = dict(row["observation"])
        row["observation"] = {**row["observation"], "revision": row["observation"]["revision"] + 1,
                              "state": state, "supplier_state": supplier_state}

    def preempt(self, request: BackendRequest, warning_seconds: int = 0):
        if type(warning_seconds) is not int or warning_seconds < 0:
            raise ValueError("warning must be nonnegative seconds")
        self._owned(request)
        def update(row):
            if row["observation"]["state"] != "running":
                raise ValueError("only a running resource may be preempted")
            if warning_seconds:
                row["deadline"] = row["clock"] + warning_seconds
                self._event(row, "interruption_notice", deadline=row["deadline"])
            else:
                self._transition(row, "lost", "released")
                self._event(row, "capacity_lost")
            return row
        self.journal.change(scope(request), update)

    def advance(self, request: BackendRequest, seconds: int):
        if type(seconds) is not int or seconds < 0:
            raise ValueError("time must advance by nonnegative seconds")
        self._owned(request)
        def update(row):
            row["clock"] += seconds
            if "deadline" in row and row["clock"] >= row["deadline"] and row["observation"]["state"] == "running":
                self._transition(row, "lost", "released")
                self._event(row, "capacity_lost")
            return row
        self.journal.change(scope(request), update)

    def release(self, request: BackendRequest):
        self._owned(request)
        def update(row):
            if row["observation"]["state"] == "released":
                return row
            if self.faults.fail_teardown:
                self._event(row, "teardown_failed")
            else:
                self._transition(row, "released", "released")
                self._event(row, "released")
            return row
        row = self.journal.change(scope(request), update)
        if row["observation"]["state"] != "released":
            raise OutcomeUnknown("simulated teardown failure; supplier may remain allocated")
        return self.observe(request)

    def events(self, request: BackendRequest, *, duplicate: bool = False):
        events = self._owned(request)["events"]
        return [event for item in events for event in ([item, item] if duplicate else [item])]


def merge_observation(current: BackendObservation, incoming: BackendObservation) -> BackendObservation:
    fields = ("tenant_id", "project_id", "account_id", "operation_id", "provider", "resource_id", "generation")
    if any(getattr(current, field) != getattr(incoming, field) for field in fields):
        raise ValueError("observation belongs to another resource, tenant or attempt")
    if incoming.revision <= current.revision:
        return current
    if current.state in {"released", "lost"} and incoming.state not in {current.state, "released"}:
        raise ValueError("terminal resource cannot be resurrected")
    return incoming
