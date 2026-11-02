from email.parser import Parser
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from zipfile import ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_version_hook", ROOT / "hatch_build.py"
)
hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook)


@pytest.fixture(autouse=True)
def clear_version_environment(monkeypatch):
    monkeypatch.delenv("TRAME_VTKJS_RELEASE_VERSION", raising=False)
    monkeypatch.delenv("TRAME_VTKJS_SHA", raising=False)


@pytest.mark.parametrize("version", ["0.1.0", "1.0.0", "12.34.56"])
def test_explicit_public_release_version(version, monkeypatch, tmp_path):
    monkeypatch.setenv("TRAME_VTKJS_RELEASE_VERSION", version)
    monkeypatch.setenv("TRAME_VTKJS_SHA", "abcdef0")
    assert hook._stamped_version(str(tmp_path)) == version


@pytest.mark.parametrize(
    "version",
    [
        "",
        "v1.2.3",
        "1.2",
        "01.2.3",
        "1.02.3",
        "1.2.3rc1",
        "1.2.3.dev1",
        "1.2.3+git.abcdef0",
        " 1.2.3",
        "1.2.3\n",
    ],
)
def test_invalid_public_release_version_refuses_fallback(
    version, monkeypatch, tmp_path
):
    monkeypatch.setenv("TRAME_VTKJS_RELEASE_VERSION", version)
    monkeypatch.setenv("TRAME_VTKJS_SHA", "abcdef0")
    with pytest.raises(ValueError, match="public X.Y.Z"):
        hook._stamped_version(str(tmp_path))


def test_development_version_retains_source_revision(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAME_VTKJS_SHA", "abcdef0")
    assert hook._stamped_version(str(tmp_path)) == "0.1.0+git.abcdef0"


@pytest.mark.parametrize(
    "metadata, error",
    [
        ("Name: another-package\nVersion: 0.2.3\n", "does not identify"),
        ("Name: trame-vtkjs\n", "valid package version"),
        ("Name: trame-vtkjs\nVersion: unknown\n", "valid package version"),
    ],
)
def test_invalid_sdist_metadata_cannot_silently_downgrade(metadata, error, tmp_path):
    (tmp_path / "PKG-INFO").write_text(metadata)
    with pytest.raises(ValueError, match=error):
        hook._stamped_version(str(tmp_path))


def test_unrelated_parent_git_revision_is_not_a_package_version(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="requires a Git checkout"):
        hook._stamped_version(str(source))


def build(source, output, target, env):
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            f"--{target}",
            "--no-isolation",
            "--outdir",
            str(output),
        ],
        cwd=source,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def wheel_contents(path):
    with ZipFile(path) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata = Parser().parsestr(archive.read(metadata_name).decode())
        runtime = {
            name: archive.read(name)
            for name in archive.namelist()
            if name.startswith(("trame_vtkjs/", "trame/")) and not name.endswith("/")
        }
    return metadata["Version"], runtime


@pytest.mark.parametrize("public", [True, False])
def test_sdist_rebuild_preserves_version_and_offline_runtime_without_git(
    tmp_path, public
):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("pyproject.toml", "hatch_build.py", "README.rst", "LICENSE"):
        shutil.copyfile(ROOT / name, source / name)
    shutil.copytree(
        ROOT / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__")
    )
    env = {**os.environ}
    env.pop("TRAME_VTKJS_RELEASE_VERSION", None)
    env.pop("TRAME_VTKJS_SHA", None)
    if public:
        version = "0.2.3"
        env["TRAME_VTKJS_RELEASE_VERSION"] = version
    else:
        version = "0.1.0+git.abcdef0"
        env["TRAME_VTKJS_SHA"] = "abcdef0"
    build(source, tmp_path / "direct", "wheel", env)
    build(source, tmp_path / "sdist", "sdist", env)
    distribution = next((tmp_path / "sdist").glob("*.tar.gz"))
    unpacked = tmp_path / "unpacked"
    with tarfile.open(distribution) as archive:
        names = archive.getnames()
        for required in (
            "hatch_build.py",
            "pyproject.toml",
            "LICENSE",
            "README.rst",
            "PKG-INFO",
        ):
            assert any(name.endswith("/" + required) for name in names)
        for member in archive.getmembers():
            relative = Path(member.name)
            assert not relative.is_absolute() and ".." not in relative.parts
            path = unpacked / relative
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                assert member.isfile()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.extractfile(member).read())
    rebuilt_source = next(unpacked.iterdir())
    env.pop("TRAME_VTKJS_RELEASE_VERSION", None)
    env.pop("TRAME_VTKJS_SHA", None)
    build(rebuilt_source, tmp_path / "rebuilt", "wheel", env)
    direct_version, direct_runtime = wheel_contents(
        next((tmp_path / "direct").glob("*.whl"))
    )
    rebuilt_version, rebuilt_runtime = wheel_contents(
        next((tmp_path / "rebuilt").glob("*.whl"))
    )
    assert direct_version == rebuilt_version == version
    assert direct_runtime == rebuilt_runtime
    for asset in (
        "js/trame_vtkjs.umd.js",
        "js/tiles3dDecodeWorker.classic.js",
        "wasm/tiles3d/draco_wasm_wrapper.js",
        "wasm/tiles3d/draco_decoder.wasm",
        "wasm/tiles3d/basis_encoder.js",
        "wasm/tiles3d/basis_encoder.wasm",
    ):
        assert "trame_vtkjs/module/serve/" + asset in rebuilt_runtime
