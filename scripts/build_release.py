"""Rebuild both distributions in fresh staging; replace only verified local artifacts."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from check_release import ROOT, check_directory


def main():
    output = ROOT / "dist"
    # Validate resolved paths before any replacement/removal on Windows or Unix.
    if output.is_symlink() or output.resolve() != ROOT.resolve() / "dist":
        raise RuntimeError("unsafe_distribution_directory")
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vgpu-release-") as temporary:
        stage = Path(temporary)
        subprocess.run(["uv", "build", "--sdist", "--wheel", "--out-dir", str(stage)], cwd=ROOT, check=True)
        results = check_directory(stage)
        for result in results:
            target = output / result["file"]
            if target.is_symlink() or target.resolve().parent != output.resolve():
                raise RuntimeError("unsafe_distribution_file")
            shutil.copyfile(stage / result["file"], target)
        names = {result["file"] for result in results}
        for stale in output.iterdir():
            if stale.name.endswith((".whl", ".tar.gz")) and stale.name not in names:
                if stale.is_symlink() or not stale.is_file() or stale.resolve().parent != output.resolve():
                    raise RuntimeError("unsafe_distribution_file")
                stale.unlink()
        print(json.dumps(check_directory(output), indent=2))


if __name__ == "__main__": main()
