"""RFC 8628 native client. Optional cloud extra; no browser listener or account token."""
import json
import os
import platform
import re
import secrets
import time
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from filelock import FileLock, Timeout

from .cloud import CloudConnection, CloudError, endpoint_url
from .contracts.models import SiteConnection, SiteEnrollment, SiteEnrollmentApproval

CLIENT = "vgpu-local"
SCOPE = "vgpu:enroll"
GRANT = "urn:ietf:params:oauth:grant-type:device_code"


class DeviceConnection:
    def __init__(self, connection: CloudConnection, *, clock=time.time, sleep=time.sleep):
        self.connection = connection
        self.clock, self.sleep = clock, sleep

    def connect(self, *, endpoint: str, name: str, announce, restart=False):
        endpoint = endpoint_url(endpoint)
        path = str(self.connection.config.resolve())
        entry = "device:" + sha256(json.dumps([endpoint, path]).encode()).hexdigest()
        self.connection.lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Lock the CONFIG path (not endpoint). Two origins cannot race to enroll it.
        lock = self.connection.lock_dir / ("device-" + sha256(path.encode()).hexdigest() + ".lock")
        try:
            with FileLock(lock, timeout=0):
                return self._connect(endpoint, name, announce, entry, restart)
        except Timeout:
            raise CloudError("connection_command_already_running") from None

    def _connect(self, endpoint, name, announce, entry, restart):
        saved = self.connection.secrets.get(entry)
        try:
            state = json.loads(saved) if saved else None
            if state and (state["endpoint"] != endpoint or state["name"] != name):
                raise CloudError("connection_config_conflict")
            if state and state["phase"] not in {"new", "requesting", "polling", "authorized", "failed"}:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise CloudError("device_state_unavailable") from None
        if self.connection.config.exists():
            if restart or not state or "settings" not in state or self.connection.settings() != state["settings"]:
                raise CloudError("connection_config_exists_use_status")
            try:
                result = self.connection.status()
            except CloudError as error:
                if str(error) not in {"cloud_authentication_or_permission_denied", "cloud_request_failed_retry_same_connection"}:
                    raise
            else:
                self.connection.secrets.set(entry, "")
                return result
        elif restart:
            # Explicit user action only. The old request expires at the server;
            # this never rewrites an enrolled site's identity or pending reports.
            state = None
        if state is None:
            key = "vgs_" + secrets.token_urlsafe(32)
            site = "sit_" + uuid4().hex
            SiteEnrollment(site_id=site, name=name, credential=key, protocol_version="vgpu.site.v1")
            state = dict(endpoint=endpoint, name=name, site_id=site, credential=key, phase="new")
        save = lambda: self.connection.secrets.set(entry, json.dumps(state, ensure_ascii=True))
        if state["phase"] == "new":
            state["phase"] = "requesting"
            save()  # Private key and ambiguous-request marker BEFORE the network.
            began = self.clock()
            status, response = self._request(endpoint, "POST", "/oauth/device_authorization", data=dict(
                client_id=CLIENT, scope=SCOPE, site_id=state["site_id"], site_name=name,
                platform=platform.system() or "Unknown", credential_sha256=sha256(state["credential"].encode()).hexdigest()))
            if status != 200:
                raise CloudError("device_authorization_failed_use_restart")
            self._validate_start(endpoint, response)
            state.update(phase="polling", device_code=response["device_code"], user_code=response["user_code"],
                         verification_uri=response["verification_uri"], deadline=began + response["expires_in"],
                         interval=response.get("interval", 5), next_poll=self.clock() + response.get("interval", 5))
            save()
        elif state["phase"] == "requesting":
            raise CloudError("device_authorization_outcome_unknown_use_restart")
        elif state["phase"] == "failed":
            raise CloudError("device_authorization_ended_use_restart")
        if state["phase"] == "polling":
            announce(state["verification_uri"], state["user_code"])
            while True:
                if self.clock() >= state["deadline"]:
                    state["phase"] = "failed"; save()
                    raise CloudError("device_code_expired_use_restart")
                self.sleep(max(0, min(state["next_poll"], state["deadline"]) - self.clock()))
                if self.clock() >= state["deadline"]:
                    continue
                # Persist the next allowed attempt BEFORE sending. A crash must
                # not reset the rate limit, even when the response was lost.
                state["next_poll"] = self.clock() + state["interval"]
                save()
                try:
                    status, response = self._request(endpoint, "POST", "/oauth/token", data=dict(
                        client_id=CLIENT, grant_type=GRANT, device_code=state["device_code"]))
                except CloudError as error:
                    if str(error) != "device_network_retry_same_connection": raise
                    state["interval"] *= 2
                    state["next_poll"] = self.clock() + state["interval"]
                    save()
                    continue
                if status == 400 and response.get("error") in {"authorization_pending", "slow_down"}:
                    if response["error"] == "slow_down": state["interval"] += 5
                    state["next_poll"] = self.clock() + state["interval"]
                    save()
                    continue
                if status != 200:
                    state["phase"] = "failed"; save()
                    error = response.get("error")
                    if error == "access_denied": raise CloudError("device_authorization_denied")
                    if error == "expired_token": raise CloudError("device_code_expired_use_restart")
                    # A lost successful token reply can produce invalid_grant on
                    # retry. Do not turn it into a fresh authorization silently.
                    raise CloudError("device_authorization_ended_use_restart")
                if (not isinstance(response.get("token_type"), str) or response["token_type"].lower() != "bearer" or response.get("scope") != SCOPE or
                    not isinstance(response.get("access_token"), str) or
                    not re.fullmatch(r"[A-Za-z0-9._~-]{1,4096}", response["access_token"]) or
                    type(response.get("expires_in")) is not int or not 1 <= response["expires_in"] <= 600 or
                    "refresh_token" in response or "id_token" in response):
                    raise CloudError("invalid_device_response")
                state.update(phase="authorized", access_token=response["access_token"], token_deadline=self.clock()+response["expires_in"])
                # Device code no longer useful; discard it before final enrollment.
                for key in ("device_code", "user_code", "verification_uri", "deadline", "interval", "next_poll"):
                    state.pop(key, None)
                save()
                break
        if state["phase"] != "authorized":
            raise CloudError("device_state_unavailable")
        if self.clock() >= state["token_deadline"]:
            raise CloudError("device_enrollment_grant_expired_check_status")
        if "settings" not in state:
            status, approved = self._request(endpoint, "GET", "/api/v1/device/approval", token=state["access_token"])
            try:
                approved = SiteEnrollmentApproval.model_validate(approved).model_dump()
            except ValueError:
                raise CloudError("device_approval_scope_mismatch") from None
            if (status != 200 or approved.get("site_id") != state["site_id"] or approved.get("name") != name or
                not re.fullmatch(r"ten_[a-z0-9]{8,64}", str(approved.get("tenant_id", ""))) or
                not re.fullmatch(r"prj_[a-z0-9]{8,64}", str(approved.get("project_id", "")))):
                raise CloudError("device_approval_scope_mismatch")
            state["settings"] = {"endpoint": endpoint, **{k: approved[k] for k in ("tenant_id", "project_id", "site_id", "name")}}
            save()
        settings = state["settings"]
        if not self.connection.config.exists():
            self.connection.secrets.set(self.connection._secret_name(settings), state["credential"])
            self.connection.config.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(self.connection.config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    json.dump(settings, output)
                    output.flush(); os.fsync(output.fileno())
            except FileExistsError:
                raise CloudError("connection_config_conflict") from None
        if self.connection.settings() != settings:
            raise CloudError("connection_config_conflict")
        body = SiteEnrollment(site_id=state["site_id"], name=name, credential=state["credential"], protocol_version="vgpu.site.v1").model_dump()
        status, response = self._request(endpoint, "POST", "/api/v1/device/enroll", token=state["access_token"], body=body)
        if status != 201: raise CloudError("device_enrollment_failed_retry_same_connection")
        try:
            result = SiteConnection.model_validate(response).model_dump()
        except ValueError:
            raise CloudError("invalid_device_response") from None
        if any(result[key] != settings[key] for key in ("tenant_id", "project_id", "site_id", "name")):
            raise CloudError("device_approval_scope_mismatch")
        self.connection.secrets.set(entry, "")  # Keep only the revocable site key.
        return result

    @staticmethod
    def _validate_start(endpoint, response):
        try:
            if (not isinstance(response["verification_uri"], str) or len(response["verification_uri"]) > 2048 or
                not re.fullmatch(r"https?://[\x21-\x7e]+", response["verification_uri"])):
                raise ValueError()
            uri = urlsplit(response["verification_uri"])
            if (uri.scheme + "://" + uri.netloc != endpoint or uri.username or uri.password or uri.fragment or
                not re.fullmatch(r"[A-Za-z0-9-]{4,64}", response["user_code"]) or
                not re.fullmatch(r"[A-Za-z0-9._~-]{1,4096}", response["device_code"]) or
                type(response["expires_in"]) is not int or not 1 <= response["expires_in"] <= 900 or
                type(response.get("interval", 5)) is not int or not 1 <= response.get("interval", 5) <= 60):
                raise ValueError()
        except (TypeError, ValueError, KeyError):
            raise CloudError("invalid_device_response") from None

    def _request(self, endpoint, method, path, *, data=None, token=None, body=None):
        try:
            with httpx.Client(transport=self.connection.transport, timeout=20, follow_redirects=False, trust_env=False) as client:
                with client.stream(method, endpoint + path, data=data, json=body,
                                   headers={"Authorization": "Bearer " + token} if token else {}) as response:
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 65536: raise CloudError("device_response_too_large")
                    if 300 <= response.status_code < 400: raise CloudError("device_redirect_refused")
                    try:
                        payload = json.loads(content)
                        if not isinstance(payload, dict): raise ValueError()
                    except (ValueError, TypeError):
                        raise CloudError("invalid_device_response") from None
                    return response.status_code, payload
        except httpx.HTTPError:
            raise CloudError("device_network_retry_same_connection") from None
