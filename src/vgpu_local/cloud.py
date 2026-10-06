"""Explicit, outbound enrollment. This never submits jobs or shares local GPUs."""
import json
import os
import secrets
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from .contracts.models import SiteConnection, SiteEnrollment


class CloudError(RuntimeError):
    """Only fixed codes reach the CLI: responses may contain credentials or HTML."""


class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, secret: str) -> None: ...


class SystemKeyring:
    def __init__(self):
        import keyring
        # Reject plaintext/third-party fallback stores. The public package requires
        # an explicitly supported OS credential store instead of silently saving keys.
        backend = keyring.get_keyring()
        if type(backend).__module__ not in {
            "keyring.backends.Windows", "keyring.backends.macOS", "keyring.backends.SecretService"
        }:
            raise CloudError("os_credential_store_unavailable")
        self.backend = backend

    def get(self, name):
        try:
            return self.backend.get_password("vgpu-local", name)
        except Exception:
            raise CloudError("os_credential_store_unavailable") from None

    def set(self, name, secret):
        try:
            self.backend.set_password("vgpu-local", name, secret)
        except Exception:
            raise CloudError("os_credential_store_unavailable") from None


def endpoint_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise CloudError("invalid_cloud_endpoint")
    if not parsed.hostname or not (parsed.scheme == "https" or
                                  (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "[::1]", "::1"})):
        raise CloudError("https_required_except_loopback")
    return value.rstrip("/")


class CloudConnection:
    def __init__(self, config: Path, secrets_store: SecretStore, *, transport=None):
        self.config = config
        self.secrets = secrets_store
        self.transport = transport

    def connect(self, *, endpoint: str, tenant_id: str, project_id: str, name: str, user_access_token: str):
        import re
        endpoint = endpoint_url(endpoint)
        if not re.fullmatch(r"ten_[a-z0-9]{8,64}", tenant_id) or not re.fullmatch(r"prj_[a-z0-9]{8,64}", project_id):
            raise CloudError("invalid_project_scope")
        if not user_access_token or any(c.isspace() for c in user_access_token):
            raise CloudError("user_access_token_required")
        settings = {"endpoint": endpoint, "tenant_id": tenant_id, "project_id": project_id, "name": name}
        if self.config.exists():
            saved = self._settings()
            if any(saved.get(k) != v for k, v in settings.items()):
                raise CloudError("connection_config_conflict")
            settings = saved
            credential = self._credential(settings)
        else:
            settings["site_id"] = "sit_" + uuid4().hex
            credential = "vgs_" + secrets.token_urlsafe(32)
            # Validate before persisting. Credentials are stored before the request:
            # retry after a lost enrollment response reuses the same installation/key.
            SiteEnrollment(site_id=settings["site_id"], name=name,
                           protocol_version="vgpu.site.v1", credential=credential)
            self.secrets.set(self._secret_name(settings), credential)
            self.config.parent.mkdir(parents=True, exist_ok=True)
            try:
                # Exclusive creation prevents two CLI processes enrolling different
                # installations through the same configuration path. No overwrite.
                fd = os.open(self.config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    json.dump(settings, file)
                    file.flush()
                    os.fsync(file.fileno())
            except FileExistsError:
                raise CloudError("connection_config_conflict") from None
        body = SiteEnrollment(site_id=settings["site_id"], name=name,
                              protocol_version="vgpu.site.v1", credential=credential).model_dump()
        return self._request(settings, "POST", "/sites", user_access_token, body)

    def status(self):
        settings = self._settings()
        return self._request(settings, "GET", f'/sites/{settings["site_id"]}/connection', self._credential(settings))

    def disconnect(self):
        settings = self._settings()
        # Keep the credential and metadata for safe retry if the response is lost.
        return self._request(settings, "POST", f'/sites/{settings["site_id"]}/connection/revoke', self._credential(settings))

    def _settings(self):
        try:
            settings = json.loads(self.config.read_text(encoding="utf-8"))
            import re
            if set(settings) != {"endpoint", "tenant_id", "project_id", "site_id", "name"}:
                raise ValueError()
            endpoint_url(settings["endpoint"])
            if not re.fullmatch(r"ten_[a-z0-9]{8,64}", settings["tenant_id"]): raise ValueError()
            if not re.fullmatch(r"prj_[a-z0-9]{8,64}", settings["project_id"]): raise ValueError()
            if not re.fullmatch(r"sit_[a-f0-9]{32}", settings["site_id"]): raise ValueError()
            return settings
        except (OSError, ValueError, TypeError, KeyError):
            raise CloudError("connection_config_unavailable") from None

    def _credential(self, settings):
        secret = self.secrets.get(self._secret_name(settings))
        if not secret:
            raise CloudError("site_credential_unavailable")
        return secret

    @staticmethod
    def _secret_name(settings):
        # A modified config must not send an existing key to a different origin.
        identity = [settings[k] for k in ("endpoint", "tenant_id", "project_id", "site_id")]
        return "site:" + sha256(json.dumps(identity).encode()).hexdigest()

    def _request(self, settings, method, suffix, token, body=None):
        base = endpoint_url(settings["endpoint"])
        url = f'{base}/api/v1/tenants/{settings["tenant_id"]}/projects/{settings["project_id"]}{suffix}'
        try:
            with httpx.Client(transport=self.transport, timeout=20, follow_redirects=False, trust_env=False) as client:
                response = client.request(method, url, headers={"Authorization": f"Bearer {token}"}, json=body)
        except httpx.HTTPError:
            raise CloudError("cloud_outcome_unknown_retry_same_connection") from None
        if response.status_code in {401, 403}:
            raise CloudError("cloud_authentication_or_permission_denied")
        if response.status_code == 409:
            raise CloudError("cloud_connection_conflict")
        if response.status_code >= 300:
            raise CloudError("cloud_request_failed_retry_same_connection")
        try:
            result = SiteConnection.model_validate(response.json())
        except ValueError:
            raise CloudError("invalid_cloud_response") from None
        if any(getattr(result, key) != settings[key] for key in ("tenant_id", "project_id", "site_id", "name")):
            raise CloudError("cloud_response_scope_mismatch")
        return result.model_dump()
