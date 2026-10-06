"""Theta GPU Node API v1. Native responses are retained rather than guessed."""
import re
from urllib.parse import quote

import httpx

from .errors import OutcomeUnknown
from .journal import ReceiptStore, fingerprint


class ThetaClient:
    def __init__(self, project_id: str, api_key: str, journal: ReceiptStore, *, transport=None):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", project_id) or not api_key:
            raise ValueError("project ID and project-scoped API key are required")
        self.project_id, self.journal = project_id, journal
        self.client = httpx.Client(
            base_url="https://controller.thetaedgecloud.com", timeout=30,
            headers={"x-api-key": api_key}, transport=transport, follow_redirects=False,
        )

    def close(self):
        self.client.close()

    def _call(self, method: str, suffix: str, **kwargs):
        try:
            response = self.client.request(method, f"/v1/projects/{self.project_id}/{suffix}", **kwargs)
        except httpx.TransportError as exc:
            if method != "GET":
                raise OutcomeUnknown("Theta mutation outcome is unknown; reconcile before retry") from exc
            raise
        if method != "GET" and response.status_code >= 500:
            raise OutcomeUnknown("Theta mutation returned a server error; reconcile before retry")
        response.raise_for_status()
        if response.status_code == 204:
            return None
        try:
            envelope = response.json()
            if envelope.get("status") != "success" or "body" not in envelope:
                raise ValueError("unexpected Theta envelope")
            return envelope["body"]
        except (ValueError, AttributeError) as exc:
            if method != "GET":
                raise OutcomeUnknown("Theta mutation returned an unreadable receipt") from exc
            raise

    def resources(self):
        return self._call("GET", "gpu-resources")

    def templates(self):
        return self._call("GET", "gpu-deployment-templates")

    def deployments(self):
        return self._call("GET", "gpu-deployments")

    @staticmethod
    def _deployment(deployment_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", deployment_id):
            raise ValueError("invalid deployment ID")
        return "gpu-deployments/" + quote(deployment_id, safe="")

    def inspect(self, deployment_id: str):
        return self._call("GET", self._deployment(deployment_id))

    def create(self, operation_id: str, *, resource_id: str, template_id: str,
               image: str, region: str, ssh_public_key: str, max_hourly_price_microusd: int):
        if not operation_id or any(not value for value in (resource_id, template_id, image, region)):
            raise ValueError("operation, resource, template, image and region are required")
        if type(max_hourly_price_microusd) is not int or not 0 < max_hourly_price_microusd <= 9007199254740991:
            raise ValueError("a positive safe-integer price ceiling is required")
        if "\n" in ssh_public_key or "\r" in ssh_public_key or not ssh_public_key.startswith(("ssh-", "ecdsa-")):
            raise ValueError("a single-line OpenSSH public key is required")
        key = fingerprint({"provider": "theta", "project": self.project_id, "operation": operation_id})
        # The native name is a correlation hint, not a claim of server idempotency.
        payload = {
            "name": "vg" + key[:18], "resource_id": resource_id,
            "deployment_template_id": template_id, "container_image": image,
            "region": region, "ssh_public_key": ssh_public_key, "ssh_port": 22,
            "max_price_per_hour_usd": max_hourly_price_microusd / 1_000_000,
        }
        created, receipt = self.journal.begin(key, payload, {"state": "uncertain", "name": payload["name"]})
        if not created:
            if receipt["state"] == "accepted":
                return receipt["response"]
            raise OutcomeUnknown("Theta create needs reconciliation; no automatic second POST")
        body = self._call("POST", "gpu-deployments", json=payload)
        self.journal.change(key, lambda row: {**row, "state": "accepted", "response": body})
        return body

    def stop(self, deployment_id: str):
        return self._call("POST", self._deployment(deployment_id) + "/stop")

    def start(self, deployment_id: str):
        return self._call("POST", self._deployment(deployment_id) + "/start")

    def delete(self, deployment_id: str):
        return self._call("DELETE", self._deployment(deployment_id))

    def events(self, deployment_id: str):
        return self._call("GET", self._deployment(deployment_id) + "/events")

    def logs(self, deployment_id: str):
        return self._call("GET", self._deployment(deployment_id) + "/logs")
