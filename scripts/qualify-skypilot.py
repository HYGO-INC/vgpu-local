"""Offline wire-model qualification in a separately installed SkyPilot environment.

No SDK request is sent and no API server is started. Run on Linux/WSL with
skypilot==0.14.0 installed; this is independent of supplier live qualification.
"""
import inspect
import json
from importlib.metadata import version

from pydantic import ValidationError
from sky.client import sdk
from sky.server.requests.payloads import StatusBody, JobStatusBody


assert version("skypilot") == "0.14.0"
arguments = dict(cluster_names=["vgqualification"], refresh="FORCE", all_users=False,
                 _include_credentials=False)
inspect.signature(sdk.status).bind(**arguments)
body = StatusBody(cluster_names=arguments["cluster_names"], refresh=arguments["refresh"],
                  all_users=False, include_credentials=False)
wire = json.loads(body.model_dump_json())
assert wire["refresh"] == "FORCE" and wire["include_credentials"] is False
inspect.signature(sdk.job_status).bind("vgqualification",job_ids=[17])
assert JobStatusBody(cluster_name="vgqualification",job_ids=[17]).model_dump()["job_ids"] == [17]
try:
    StatusBody(cluster_names=["vgqualification"], refresh=True)
except ValidationError:
    boolean_rejected = True
else:
    boolean_rejected = False
assert boolean_rejected, "Revisit the adapter if upstream changes its refresh wire format"
print(json.dumps(dict(skypilot=version("skypilot"), status_signature="passed",
                     status_wire="passed", job_status_wire="passed", boolean_refresh="rejected", provider_calls=0)))
