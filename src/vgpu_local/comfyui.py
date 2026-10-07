"""Thin local ComfyUI queue adapter. A prompt ID is correlation, NOT idempotence."""
from urllib.parse import urlsplit

import httpx


def loopback_url(endpoint):
    try:
        url = urlsplit(endpoint)
        if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1"} or not url.port
                or url.username is not None or url.password is not None
                or url.path not in {"", "/"} or url.query or url.fragment):
            raise ValueError()
    except ValueError:
        raise ValueError("explicit_loopback_http_endpoint_required") from None
    return endpoint.rstrip("/")


class EngineError(RuntimeError):
    pass


class ComfyEngine:
    def __init__(self, endpoint, *, transport=None):
        self.endpoint = loopback_url(endpoint)
        self.transport = transport

    def request(self, method, path, body=None):
        try:
            with httpx.Client(transport=self.transport, timeout=10, trust_env=False,
                              follow_redirects=False) as client:
                with client.stream(method, self.endpoint+path, json=body) as response:
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > 8_000_000: raise EngineError("engine_response_too_large")
                    import json
                    return response.status_code, json.loads(data)
        except (httpx.HTTPError, ValueError):
            raise EngineError("engine_outcome_unknown") from None

    @staticmethod
    def marker(job):
        return {k: job[k] for k in ("execution_id", "correlation", "recipe_sha256")}

    def submit(self, job):
        status, result = self.request("POST", "/prompt", {
            "prompt_id": job["engine_job_id"], "prompt": job["prompt"],
            "extra_data": {"vgpu_local": self.marker(job)},
        })
        # Only an explicit validation rejection proves no prompt was accepted.
        if status == 400 and isinstance(result, dict) and "error" in result:
            return {"state": "failed", "error_code": "engine_rejected_workflow"}
        if status != 200 or not isinstance(result, dict) or result.get("prompt_id") != job["engine_job_id"]:
            raise EngineError("engine_submission_unconfirmed")
        return {"state": "queued", "error_code": None}

    def matches(self, entry, job):
        return (isinstance(entry, list) and len(entry) >= 4 and entry[1] == job["engine_job_id"]
                and isinstance(entry[3], dict) and entry[3].get("vgpu_local") == self.marker(job))

    def observe(self, job):
        status, history = self.request("GET", "/history/"+job["engine_job_id"])
        if status != 200 or not isinstance(history, dict): raise EngineError("engine_history_unavailable")
        completed = history.get(job["engine_job_id"])
        if completed is not None:
            if not isinstance(completed, dict) or not self.matches(completed.get("prompt"), job):
                raise EngineError("engine_identity_conflict")
            result = completed.get("status", {})
            if result.get("completed") and result.get("status_str") == "success":
                # Output metadata remains owner-local; never fetch or upload files.
                return {"state": "succeeded", "outputs": completed.get("outputs", {}), "error_code": None}
            if result.get("status_str") == "error":
                interrupted = any(isinstance(m, list) and m and m[0] == "execution_interrupted"
                                  for m in result.get("messages", []))
                return {"state": "canceled" if interrupted else "failed", "error_code": "engine_interrupted" if interrupted else "engine_execution_failed"}
        status, queue = self.request("GET", "/queue")
        if status != 200 or not isinstance(queue, dict): raise EngineError("engine_queue_unavailable")
        for field, state in (("queue_running", "running"), ("queue_pending", "queued")):
            if not isinstance(queue.get(field), list): raise EngineError("engine_queue_unavailable")
            for entry in queue[field]:
                if isinstance(entry, list) and len(entry) > 1 and entry[1] == job["engine_job_id"]:
                    if not self.matches(entry, job): raise EngineError("engine_identity_conflict")
                    return {"state": state, "error_code": None}
        # Missing/pruned history is not proof that the create never reached ComfyUI.
        return {"state": "uncertain", "error_code": "engine_job_not_observed"}

    def cancel(self, job):
        # New ComfyUI targeted route atomically identifies the running prompt.
        # Never fall back to /interrupt: older engines interrupt an unrelated job.
        status, result = self.request("POST", "/api/jobs/"+job["engine_job_id"]+"/cancel", {})
        if status == 404: raise EngineError("engine_targeted_cancel_unavailable")
        if status != 200 or not isinstance(result, dict) or not isinstance(result.get("cancelled"), bool):
            raise EngineError("engine_cancellation_unconfirmed")
        return result["cancelled"]
