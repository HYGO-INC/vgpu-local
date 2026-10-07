import json
from pathlib import Path
import subprocess

from jsonschema import Draft202012Validator
from pydantic import ValidationError
from referencing import Registry, Resource

from vgpu_local.contracts import models


def test_shared_protocol_corpus():
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "protocol/fixtures.json").read_text())
    bundle = json.loads((root / "protocol/generated/resources.json").read_text())
    for name, definition in bundle["$defs"].items():
        if definition.get("type") == "object":
            for valid in (True, False):
                assert any(c["contract"] == name and c["valid"] == valid for c in cases), (name, valid)
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema))
                                         for schema in bundle["$defs"].values())
    output = subprocess.check_output(["node", "protocol/oracle.cjs"], cwd=root, text=True)
    ts_verdicts = json.loads(output)
    assert len(ts_verdicts) == len(cases)
    for case, ts in zip(cases, ts_verdicts):
        schema_valid = Draft202012Validator(bundle["$defs"][case["contract"]], registry=registry).is_valid(case["document"])
        try:
            parsed = getattr(models, case["contract"]).model_validate(case["document"])
            assert parsed.model_dump(mode="json") == case["document"]
            py_valid = True
        except ValidationError:
            py_valid = False
        assert schema_valid == ts == py_valid == case["valid"], case["name"]
