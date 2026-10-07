"""Install the built starter in a clean environment without contacting an index."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path)
    args = parser.parse_args()
    wheels = [args.wheel] if args.wheel else sorted(Path("dist").glob("*.whl"))
    if len(wheels) != 1:
        parser.error("supply one built wheel with --wheel")
    wheel = wheels[0].resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="vgpu-starter-") as directory:
        environment = Path(directory)/"venv"
        subprocess.run(["uv", "venv", "--python", sys.executable, str(environment)], check=True)
        python = environment/("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        # No --no-deps: accidental mandatory dependencies must fail resolution.
        subprocess.run(["uv", "pip", "install", "--no-index", "--python", str(python), str(wheel)], check=True)
        check = "import importlib.metadata as m; import json; print(json.dumps(sorted(d.metadata['Name'] for d in m.distributions())))"
        installed = json.loads(subprocess.check_output([str(python), "-I", "-c", check], text=True))
        assert installed == ["vgpu-local"], installed
        command = [str(python), "-I", "-c", "from vgpu_local.cli import main; main()"]
        result = json.loads(subprocess.check_output([*command, "doctor", "--no-probe"], text=True))
        assert not result["account_required"] and not result["kubernetes_required"] and not result["downloads_started"]
        optional = subprocess.run([*command, "cloud", "status"], capture_output=True, text=True)
        assert optional.returncode == 2 and "vgpu-local[cloud]" in optional.stderr
        optional_runtime = subprocess.run([*command, "runtime", "status"], capture_output=True, text=True)
        assert optional_runtime.returncode == 2 and "vgpu-local[runtime]" in optional_runtime.stderr
        print(json.dumps({"wheel": wheel.name, "bytes": wheel.stat().st_size,
                          "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                          "installed_distributions": installed,
                          "doctor": "passed", "optional_dependency_message": "passed",
                          "python_included_in_size": False}, indent=2))


if __name__ == "__main__": main()
