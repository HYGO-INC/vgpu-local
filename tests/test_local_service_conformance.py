"""Run shared attack vectors over the real Uvicorn HTTP listener."""
import hashlib
import http.client
import json
from pathlib import Path
import re
import sys

import pytest

from runtime_fixture import EngineFixture, listener_addresses, service, setup

DIRECTORY = Path(__file__).parent / "fixtures/local-services"
CORPUS = json.loads((DIRECTORY / "cases.json").read_text(encoding="utf-8"))
PROFILE = "local-http-bearer"


def test_shared_corpus_pin():
    pin = json.loads((DIRECTORY / "upstream.json").read_text(encoding="utf-8"))
    assert pin["artifact"] == "local-service-conformance" and pin["schemaVersion"] == 1
    assert pin["version"] == CORPUS["version"] and CORPUS["schemaVersion"] == 1
    assert re.fullmatch(r"[0-9a-f]{40}", pin["upstream"]["commit"])
    assert set(pin["files"]) == {"cases.json", "README.md", "LICENSE"}
    assert {p.name for p in DIRECTORY.iterdir()} == {*pin["files"], "upstream.json"}
    for name, digest in pin["files"].items():
        assert hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest() == digest
    assert PROFILE in CORPUS["profiles"]
    assert {c["allow"][PROFILE] for c in CORPUS["cases"] if PROFILE in c["allow"]} == {True, False}


@pytest.fixture(scope="module")
def local_service(tmp_path_factory):
    with EngineFixture() as engine:
        path = tmp_path_factory.mktemp("boundary") / "runtime"
        setup(path, engine)
        with service(path) as (info, _):
            port = int(info["origin"].rsplit(":", 1)[1])
            yield info, port


@pytest.mark.skipif(sys.platform != "win32" and not sys.platform.startswith("linux"),
                    reason="OS listener inspection supports Windows and Linux")
def test_local_service_listener(local_service):
    info, port = local_service
    assert set(listener_addresses(info["pid"], port)) == {"127.0.0.1"}


@pytest.mark.parametrize("case", [c for c in CORPUS["cases"] if PROFILE in c["allow"]], ids=lambda c: c["id"])
def test_local_service_attack(case, local_service):
    info, port = local_service
    values = {"authority": f"127.0.0.1:{port}", "port": str(port),
              "allowed_origin": info["origin"], "token": info["token"],
              "other_scheme_origin": f"https://127.0.0.1:{port}",
              "other_port_origin": "http://127.0.0.1:1"}
    replaced = {k.lower() for k in case["headers"]}
    headers = [(k, vs) for k, vs in CORPUS["baseHeaders"].items() if k.lower() not in replaced]
    headers += list(case["headers"].items())
    # putheader preserves duplicates; skip_host prevents the client inserting a
    # missing Host. No harness-side Origin, Host or bearer validation.
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.putrequest("GET", "/api/status", skip_host=True, skip_accept_encoding=True)
        for key, items in headers:
            for item in items:
                connection.putheader(key, item.format_map(values))
        connection.endheaders()
        response = connection.getresponse()
        response.read()
        if case["allow"][PROFILE]:
            assert response.status == 200
        else:
            assert 400 <= response.status < 500
    finally:
        connection.close()
