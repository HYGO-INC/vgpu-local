"""Durable interruption exchange; the external backend still owns reclamation.

The controller methods are a trusted port, not a workload API. A file/HTTP
forwarder can call only respond with a separately authenticated participant.
This module never kills a process, creates capacity or changes a financial ledger.
"""
from copy import deepcopy

from .contracts.models import (
    Interruption, InterruptionEvent, InterruptionReceipt, InterruptionRequest,
    InterruptionScope, InterruptionSnapshot, InterruptionSourceNotice,
)
from .errors import KeyConflict
from .journal import ReceiptStore, fingerprint


class InterruptionConflict(RuntimeError):
    pass


def _source_rules(source: InterruptionSourceNotice):
    actions = source.allowed_actions
    if len(actions) != len(set(actions)):
        raise ValueError("duplicate interruption action")
    action, before = source.source_action_at_ms, source.source_not_before_ms
    if ((source.source_time_kind == "action_at" and (action is None or before is not None))
            or (source.source_time_kind == "not_before" and (before is None or action is not None))
            or (source.source_time_kind in {"vgpu_policy", "unknown"} and (action is not None or before is not None))):
        raise ValueError("source timing does not match its declared semantics")
    if source.release_by_ms is not None and source.signal_at_ms is not None and source.signal_at_ms > source.release_by_ms:
        raise ValueError("stop signal cannot follow the release target")
    if source.kind == "advisory" and (set(actions) - {"ack"} or source.release_by_ms is not None or source.signal_at_ms is not None):
        raise ValueError("an advisory cannot authorize reclamation")
    if "request_extension" in actions:
        if (source.authority == "provider" or source.release_by_ms is None or source.extension_limit_ms is None
                or source.extension_limit_ms <= source.release_by_ms):
            raise ValueError("this authority cannot grant an extension")
    elif source.extension_limit_ms is not None:
        raise ValueError("extension limit without extension capability")


class InterruptionController:
    """One immutable runtime scope and an explicit set of required participants.

    The ReceiptStore serializes all transitions, including ready versus cancel
    and extension versus release. Its commit must finish before publishing files
    or returning a receipt. Deployment must fence an old controller externally;
    a generation number alone does not revoke GPU or shared-volume access.
    """
    def __init__(self, store: ReceiptStore, scope: InterruptionScope, participants: list[str]):
        scope = InterruptionScope.model_validate(scope.model_dump())
        if (not participants or len(participants) > 64 or len(participants) != len(set(participants))
                or any(not isinstance(item, str) or not 1 <= len(item) <= 255 for item in participants)):
            raise ValueError("provide 1-64 unique, expected participant identities")
        self.store, self.scope = store, scope
        self.key = fingerprint({"interruption_runtime": scope.model_dump()})
        self.participants = frozenset(participants)
        store.begin(self.key, {"scope": scope.model_dump(), "participants": sorted(participants)},
                    {"cursor": 0, "notices": {}, "requests": {}, "grants": {}, "events": [], "release_evidence": {}, "authorizations": {}, "closed": False})

    def snapshot(self) -> InterruptionSnapshot:
        row = self.store.read(self.key)
        return InterruptionSnapshot.model_validate({**self.scope.model_dump(), "schema_version": 1,
            "cursor": row["cursor"], "interruptions": sorted(row["notices"].values(), key=lambda value: value["interruption_id"])})

    def events(self, after_cursor: int = 0, limit: int = 100) -> list[tuple[int, InterruptionEvent]]:
        if type(after_cursor) is not int or after_cursor < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid event replay bounds")
        return [(entry["cursor"], InterruptionEvent.model_validate(entry["event"])) for entry in
                self.store.read(self.key)["events"] if entry["cursor"] > after_cursor][:limit]

    def publish(self, source: InterruptionSourceNotice) -> Interruption:
        """Trusted source update. Unknown/read-error observations never call this."""
        source = InterruptionSourceNotice.model_validate(source.model_dump())
        _source_rules(source)
        identity = "int_" + fingerprint({"runtime": self.key, "source": source.source_id, "event": source.source_event_id})[:32]
        document = source.model_dump(mode="json")
        def update(row):
            previous = row["notices"].get(identity)
            if previous:
                prior = previous["source"]
                if source.source_revision < prior["source_revision"]: return row
                if source.source_revision == prior["source_revision"]:
                    if prior != document: raise KeyConflict("source revision was reused with different content")
                    return row
                if source.authority != prior["authority"]:
                    raise InterruptionConflict("source authority cannot change within one notice")
                if previous["phase"] == "canceled" and source.state == "active":
                    raise InterruptionConflict("a canceled notice cannot be revived; use a new source event")
            elif len(row["notices"]) >= 128:
                raise InterruptionConflict("runtime notice limit reached; retain history and rotate the runtime")
            phase = previous["phase"] if previous else "scheduled"
            if source.state == "withdrawn" and phase == "scheduled": phase = "canceled"
            if row["closed"] and phase == "scheduled": phase = "completed"
            notice = {**self.scope.model_dump(), "schema_version": 1, "interruption_id": identity,
                      "version": previous["version"] + 1 if previous else 1, "phase": phase,
                      "source": document, "release_by_ms": source.release_by_ms, "signal_at_ms": source.signal_at_ms}
            self._changed(row, notice)
            return row
        row = self.store.change(self.key, update)
        return Interruption.model_validate(row["notices"][identity])

    def respond(self, request: InterruptionRequest, *, participant_id: str) -> InterruptionReceipt:
        """Workload port; participant_id comes from the authenticated channel."""
        request = InterruptionRequest.model_validate(request.model_dump())
        if ({key: getattr(request, key) for key in InterruptionScope.model_fields} != self.scope.model_dump()
                or participant_id not in self.participants or request.participant_id != participant_id):
            raise PermissionError("response is outside this participant's current runtime")
        document = request.model_dump(mode="json")
        digest = fingerprint(document)
        def update(row):
            previous = row["requests"].get(request.request_id)
            if previous:
                if previous["fingerprint"] != digest: raise KeyConflict("response request identity reused")
                return row
            if len(row["requests"]) >= 4096: raise InterruptionConflict("runtime response limit reached")
            notice = row["notices"].get(request.interruption_id)
            code = self._request_error(notice, request)
            row["cursor"] += 1
            receipt = InterruptionReceipt.model_validate({**self.scope.model_dump(), "schema_version": 1,
                "request_id": request.request_id, "interruption_id": request.interruption_id,
                "participant_id": participant_id, "action": request.action,
                "request_fingerprint": "sha256:" + digest,
                "status": "rejected" if code else "accepted", "code": code or "recorded",
                "notice_version": notice["version"] if notice else None, "cursor": row["cursor"],
                "checkpoint_status": "unverified" if not code and request.checkpoint_manifest is not None else "none"})
            row["requests"][request.request_id] = {"fingerprint": digest, "request": document, "receipt": receipt.model_dump()}
            return row
        row = self.store.change(self.key, update)
        return InterruptionReceipt.model_validate(row["requests"][request.request_id]["receipt"])

    @staticmethod
    def _request_error(notice, request):
        if not notice: return "notice_not_found"
        if notice["version"] != request.interruption_version: return "stale_notice"
        if notice["phase"] != "scheduled": return "notice_not_scheduled"
        if request.action not in notice["source"]["allowed_actions"]: return "action_not_allowed"
        if request.action != "ready" and request.checkpoint_manifest is not None: return "invalid_action_payload"
        if request.action != "request_extension" and request.requested_release_by_ms is not None: return "invalid_action_payload"
        if request.action == "request_extension":
            target, current, maximum = request.requested_release_by_ms, notice["release_by_ms"], notice["source"]["extension_limit_ms"]
            if target is None or current is None or maximum is None or not current < target <= maximum:
                return "extension_out_of_bounds"
        return None

    def authorize_release(self, interruption_id: str, expected_version: int, now_ms: int) -> Interruption:
        """Reclaim authority only: all expected ranks are ready, or time is due.

        This commits intent before the backend acts. It does not prove that
        anything stopped. A later withdrawal cannot undo this authorization.
        """
        if type(now_ms) is not int or not 0 <= now_ms <= 9007199254740991: raise ValueError("invalid current time")
        def update(row):
            prior = row["authorizations"].get(interruption_id)
            if prior:
                if prior["expected_version"] != expected_version: raise InterruptionConflict("release version changed")
                return row
            notice = self._current(row, interruption_id, expected_version)
            if notice["phase"] != "scheduled" or notice["source"]["kind"] == "advisory":
                raise InterruptionConflict("notice cannot authorize reclaim")
            ready = {entry["request"]["participant_id"] for entry in row["requests"].values()
                     if entry["receipt"]["status"] == "accepted" and entry["request"]["action"] == "ready"
                     and entry["request"]["interruption_id"] == interruption_id
                     and entry["request"]["interruption_version"] == expected_version}
            due = notice["signal_at_ms"] if notice["signal_at_ms"] is not None else notice["release_by_ms"]
            if ready != self.participants and (due is None or now_ms < due):
                raise InterruptionConflict("required participants are not ready and no known limit is due")
            notice.update(phase="releasing", version=notice["version"] + 1)
            self._changed(row, notice)
            row["authorizations"][interruption_id] = {"expected_version": expected_version, "notice": deepcopy(notice)}
            return row
        return Interruption.model_validate(self.store.change(self.key, update)["authorizations"][interruption_id]["notice"])

    def grant_extension(self, request_id: str, expected_version: int) -> Interruption:
        """Explicit reclaim-authority grant; never an automatic request side effect."""
        def update(row):
            prior = row["grants"].get(request_id)
            if prior:
                if prior["expected_version"] != expected_version: raise KeyConflict("grant retry changed its version")
                return row
            entry = row["requests"].get(request_id)
            if not entry or entry["receipt"]["status"] != "accepted" or entry["request"]["action"] != "request_extension":
                raise InterruptionConflict("no accepted extension request")
            request = entry["request"]
            notice = self._current(row, request["interruption_id"], expected_version)
            if (notice["phase"] != "scheduled" or notice["source"]["authority"] == "provider"
                    or request["interruption_version"] != expected_version):
                raise InterruptionConflict("extension request is no longer grantable")
            target = request["requested_release_by_ms"]
            signal = notice["signal_at_ms"]
            if signal is not None: signal += target - notice["release_by_ms"]
            for other in row["notices"].values():
                if other["interruption_id"] == notice["interruption_id"] or other["source"]["kind"] == "advisory": continue
                if other["phase"] == "releasing" or (other["phase"] == "scheduled" and
                        (other["release_by_ms"] is None or other["release_by_ms"] < target
                         or (signal is not None and other["signal_at_ms"] is not None and other["signal_at_ms"] < signal))):
                    raise InterruptionConflict("another active source prevents this extension")
            notice["signal_at_ms"] = signal
            notice.update(release_by_ms=target, version=notice["version"] + 1)
            self._changed(row, notice)
            row["grants"][request_id] = {"expected_version": expected_version, "notice": deepcopy(notice)}
            return row
        return Interruption.model_validate(self.store.change(self.key, update)["grants"][request_id]["notice"])

    def confirm_released(self, interruption_id: str, expected_version: int, *, backend_evidence_id: str) -> Interruption:
        """Trusted backend observation port, never a guest acknowledgement."""
        if not isinstance(backend_evidence_id, str) or not 1 <= len(backend_evidence_id) <= 255:
            raise ValueError("verified backend evidence identity is required")
        def update(row):
            prior = row["release_evidence"].get(interruption_id)
            if prior:
                if prior != {"expected_version": expected_version, "evidence_id": backend_evidence_id}:
                    raise KeyConflict("release confirmation identity changed")
                return row
            notice = self._current(row, interruption_id, expected_version)
            if notice["phase"] != "releasing": raise InterruptionConflict("release has not been authorized")
            row["closed"] = True
            # Every notice is scoped to this same allocation/attempt. Confirmed
            # reclamation closes all remaining active constraints, not one slot.
            for active in list(row["notices"].values()):
                if active["phase"] in {"scheduled", "releasing"}:
                    active = {**active, "phase": "completed", "version": active["version"] + 1}
                    self._changed(row, active)
            row["release_evidence"][interruption_id] = {"expected_version": expected_version, "evidence_id": backend_evidence_id}
            return row
        return Interruption.model_validate(self.store.change(self.key, update)["notices"][interruption_id])

    def _changed(self, row, notice):
        notice = Interruption.model_validate(notice).model_dump(mode="json")
        row["cursor"] += 1
        row["notices"][notice["interruption_id"]] = notice
        event = InterruptionEvent.model_validate({"specversion": "1.0",
            "id": "ice_" + fingerprint({"runtime": self.key, "notice": notice["interruption_id"], "version": notice["version"]}),
            "source": "urn:vgpu:interruptions", "type": "com.vgpu.interruption.changed.v1",
            "subject": f"allocations/{self.key}/interruptions/{notice['interruption_id']}",
            "datacontenttype": "application/json", "data": notice})
        row["events"].append({"cursor": row["cursor"], "event": event.model_dump(mode="json")})

    @staticmethod
    def _current(row, identity, expected):
        notice = row["notices"].get(identity)
        if not notice or notice["version"] != expected: raise InterruptionConflict("notice version changed")
        return deepcopy(notice)
