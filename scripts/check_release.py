"""Verify release archives against the current runtime, without extracting them."""
import argparse
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def check_archive(path: Path, root: Path = ROOT) -> dict:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    prefix = f"vgpu_local-{version}"
    if path.name == f"{prefix}-py3-none-any.whl":
        kind = "wheel"
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(set(names)) != len(names): raise ValueError("duplicate_archive_member")
            if any(member.file_size > 2_000_000 for member in archive.infolist()):
                raise ValueError("oversized_archive_member")
            files = {name: archive.read(name) for name in names}
        expected = {p.relative_to(root / "src").as_posix(): p.read_bytes()
                    for p in (root / "src/vgpu_local").rglob("*.py")}
        for name in ("LICENSE", "NOTICE"):
            expected[f"{prefix}.dist-info/licenses/{name}"] = (root / name).read_bytes()
        generated = {f"{prefix}.dist-info/{name}" for name in ("METADATA", "WHEEL", "entry_points.txt", "RECORD")}
        metadata_key = f"{prefix}.dist-info/METADATA"
    elif path.name == f"{prefix}.tar.gz":
        kind = "sdist"
        with tarfile.open(path) as archive:
            members = archive.getmembers()
            names = [m.name for m in members]
            if len(set(names)) != len(names): raise ValueError("duplicate_archive_member")
            if any(not m.isfile() or m.size > 2_000_000 for m in members):
                raise ValueError("unexpected_archive_member")
            files = {m.name: archive.extractfile(m).read() for m in members}
        expected = {f"{prefix}/" + p.relative_to(root).as_posix(): p.read_bytes()
                    for p in (root / "src/vgpu_local").rglob("*.py")}
        for name in ("pyproject.toml", "README.md", "LICENSE", "NOTICE", ".gitignore"):
            expected[f"{prefix}/{name}"] = (root / name).read_bytes()
        generated = {f"{prefix}/PKG-INFO"}
        metadata_key = f"{prefix}/PKG-INFO"
    else:
        raise ValueError("unexpected_archive_filename")
    if any(".." in PurePosixPath(name).parts or "\\" in name or name.startswith("/") for name in files):
        raise ValueError("unsafe_archive_path")
    if set(files) != set(expected) | generated:
        raise ValueError("archive_members_differ_from_current_source")
    if any(files[name] != content for name, content in expected.items()):
        raise ValueError("archive_bytes_differ_from_current_source")
    for name, data in files.items():
        if "/vgpu_local/" in "/" + name and name.endswith(".py"):
            if PurePosixPath(name).name in {"theta.py", "skypilot_backend.py", "overflow.py"} or any(
                marker in data for marker in (b"class ThetaClient", b"class SkyPilotBackend", b"def overflow_denials")
            ):
                raise ValueError("supplier_implementation_in_local_package")
    metadata = BytesParser().parsebytes(files[metadata_key])
    if metadata["Name"] != "vgpu-local" or metadata["Version"] != version:
        raise ValueError("package_identity_mismatch")
    if project.get("dependencies", []) or any(
        not re.fullmatch(r".+; extra == ['\"](?:cloud|control|kubernetes)['\"]", dependency)
        for dependency in metadata.get_all("Requires-Dist", [])
    ):
        raise ValueError("mandatory_or_unrecognized_runtime_dependency")
    return {"file": path.name, "kind": kind, "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "members": len(files)}


def check_directory(directory: Path, root: Path = ROOT) -> list[dict]:
    archives = sorted(p for p in directory.iterdir() if p.name.endswith((".whl", ".tar.gz")))
    if len(archives) != 2: raise ValueError("one_current_wheel_and_sdist_required")
    results = [check_archive(path, root) for path in archives]
    if {result["kind"] for result in results} != {"wheel", "sdist"}:
        raise ValueError("one_current_wheel_and_sdist_required")
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    print(json.dumps(check_directory(args.directory), indent=2))


if __name__ == "__main__": main()
