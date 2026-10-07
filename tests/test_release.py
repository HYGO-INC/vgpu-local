"""Build real archives, then reproduce stale or accidentally contaminated releases."""
import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_release", ROOT / "scripts/check_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.fixture(scope="module")
def distributions(tmp_path_factory):
    output = tmp_path_factory.mktemp("release")
    subprocess.run(["uv", "build", "--sdist", "--wheel", "--out-dir", str(output)],
                   cwd=ROOT, check=True, capture_output=True)
    return output


def rewrite(archive, change):
    if archive.suffix == ".whl":
        with zipfile.ZipFile(archive) as source:
            members = {name: source.read(name) for name in source.namelist()}
        change(members)
        with zipfile.ZipFile(archive, "w") as output:
            for name, content in members.items():
                output.writestr(name, content)
    else:
        with tarfile.open(archive) as source:
            members = {m.name: source.extractfile(m).read() for m in source.getmembers()}
        change(members)
        with tarfile.open(archive, "w:gz") as output:
            for name, content in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(content)
                output.addfile(info, io.BytesIO(content))


def test_current_archives_contain_only_current_public_runtime(distributions):
    results = release.check_directory(distributions)
    assert {result["kind"] for result in results} == {"wheel", "sdist"}


def test_source_archive_can_build_the_same_minimal_wheel(distributions, tmp_path):
    source = next(distributions.glob("*.tar.gz"))
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_path), str(source)],
                   cwd=ROOT, check=True, capture_output=True)
    result = release.check_archive(next(tmp_path.glob("*.whl")))
    assert result["kind"] == "wheel"


@pytest.mark.parametrize("suffix", [".whl", ".tar.gz"])
@pytest.mark.parametrize("problem", ["supplier", "private_plan", "old_runtime", "required_dependency"])
def test_contaminated_or_stale_artifact_is_rejected(distributions, tmp_path, suffix, problem):
    original = next(p for p in distributions.iterdir() if p.name.endswith(suffix))
    candidate = tmp_path / original.name
    shutil.copyfile(original, candidate)

    def change(members):
        cli = next(name for name in members if name.endswith("vgpu_local/cli.py"))
        metadata = next(name for name in members if name.endswith(("METADATA", "PKG-INFO")))
        if problem == "supplier":
            members[cli.replace("cli.py", "theta.py")] = b"class ThetaClient: pass\n"
        elif problem == "private_plan":
            members["private-plan.md"] = b"internal implementation plan\n"
        elif problem == "old_runtime":
            members[cli] += b"\n# previous runtime version\n"
        else:
            members[metadata] = b"Requires-Dist: requests\n" + members[metadata]
    rewrite(candidate, change)
    with pytest.raises(ValueError, match="archive_|runtime_dependency"):
        release.check_archive(candidate)


def test_extra_old_version_must_not_survive_in_release_directory(distributions, tmp_path):
    for archive in distributions.iterdir():
        shutil.copyfile(archive, tmp_path / archive.name)
    (tmp_path / "vgpu_local-0.0.0.tar.gz").write_bytes(b"stale build")
    with pytest.raises(ValueError, match="one_current_wheel_and_sdist_required"):
        release.check_directory(tmp_path)
