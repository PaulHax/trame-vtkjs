import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from types import SimpleNamespace
from zipfile import ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_artifacts", ROOT / "release_artifacts.py"
)
artifacts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(artifacts)
COMMIT = "a" * 40


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def package_metadata(version, name="trame-vtkjs"):
    return f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n".encode()


def write_wheel(state):
    with ZipFile(state.wheel, "w") as archive:
        for name, content in state.wheel_files.items():
            archive.writestr(name, content)


def write_sdist(state):
    with tarfile.open(state.sdist, "w:gz") as archive:
        for name, content in state.sdist_files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))


def make_artifacts(directory, version="0.2.3", *, commit=COMMIT, tree="b" * 40):
    directory.mkdir(parents=True, exist_ok=True)
    info = {
        "bridgeCommit": commit,
        "bridgeSource": {"commit": commit, "tree": tree, "dirty": False},
        "bundle": {
            "sha256": artifacts.digest(b"qualified UMD"),
            "bytes": len(b"qualified UMD"),
        },
        "pointcloudLod": {"version": "0.12.6"},
        "vtkjs": {"commit": "c" * 40},
    }
    runtime = {name: b"qualified runtime" for name in artifacts.REQUIRED_RUNTIME}
    runtime[artifacts.UMD] = b"qualified UMD"
    runtime[artifacts.BUILD_INFO] = encode(info)
    runtime["trame_vtkjs/py.typed"] = b""
    prefix = f"trame_vtkjs-{version}/"
    state = SimpleNamespace(
        version=version,
        directory=directory,
        wheel=directory / f"trame_vtkjs-{version}-py3-none-any.whl",
        sdist=directory / f"trame_vtkjs-{version}.tar.gz",
        build_info=directory / "build-info.json",
        evidence=directory / "release-evidence.json",
        info=info,
        prefix=prefix,
        wheel_files={
            **runtime,
            f"trame_vtkjs-{version}.dist-info/METADATA": package_metadata(version),
        },
        sdist_files={
            **{prefix + "src/" + name: content for name, content in runtime.items()},
            prefix + "PKG-INFO": package_metadata(version),
            **{
                prefix + name: b"source metadata"
                for name in (
                    "hatch_build.py",
                    "pyproject.toml",
                    "README.md",
                    "LICENSE",
                )
            },
        },
    )
    state.build_info.write_bytes(encode(info))
    write_wheel(state)
    write_sdist(state)
    return state


@pytest.fixture
def release(tmp_path):
    return make_artifacts(tmp_path)


def record(state, **overrides):
    kwargs = {
        "wheel": state.wheel,
        "sdist": state.sdist,
        "build_info": state.build_info,
        "commit": COMMIT,
        "tag": artifacts.expected_tag(state.version, COMMIT),
        "output": state.evidence,
        "version": state.version if "+" not in state.version else None,
    }
    return artifacts.record(**{**kwargs, **overrides})


def rewrite_info(state):
    content = encode(state.info)
    state.build_info.write_bytes(content)
    state.wheel_files[artifacts.BUILD_INFO] = content
    state.sdist_files[state.prefix + "src/" + artifacts.BUILD_INFO] = content
    write_wheel(state)
    write_sdist(state)


def test_record_and_verify_the_same_public_wheel_and_sdist(release):
    evidence = record(release)
    assert evidence["wheel"] == {
        "name": release.wheel.name,
        "sha256": artifacts.sha256(release.wheel),
        "version": "0.2.3",
        "tag": "trame-vtkjs-v0.2.3",
    }
    assert evidence["sdist"]["sha256"] == artifacts.sha256(release.sdist)
    assert artifacts.verify(release.evidence, release.directory, COMMIT) == evidence


def test_development_version_binds_its_source_commit(tmp_path):
    release = make_artifacts(tmp_path, "0.1.0+git.aaaaaaa")
    evidence = record(release)
    assert evidence["wheel"]["tag"] == "v0.1.0-git.aaaaaaa"
    assert artifacts.verify(release.evidence, release.directory, COMMIT) == evidence


def test_public_record_requires_the_explicit_requested_version(release):
    with pytest.raises(artifacts.ArtifactError, match="requires --version"):
        record(release, version=None)
    assert not release.evidence.exists()


@pytest.mark.parametrize("version", ["0.2.4", "0.2.3+git.aaaaaaa", "v0.2.3"])
def test_requested_version_must_match_a_canonical_public_version(release, version):
    with pytest.raises(artifacts.ArtifactError, match="requested public version"):
        record(release, version=version)


@pytest.mark.parametrize("dirty", [True, None])
def test_dirty_or_missing_source_cleanliness_refuses_evidence(release, dirty):
    release.info["bridgeSource"]["dirty"] = dirty
    rewrite_info(release)
    with pytest.raises(artifacts.ArtifactError, match="clean source"):
        record(release)


def test_wrong_source_commit_is_rejected(release):
    with pytest.raises(artifacts.ArtifactError, match="source commit"):
        record(release, commit="d" * 40)


def test_wrong_release_tag_is_rejected(release):
    with pytest.raises(artifacts.ArtifactError, match="release tag"):
        record(release, tag="trame-vtkjs-v0.2.4")


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_tampered_distribution_is_rejected_before_reading_it(release, kind):
    record(release)
    path = getattr(release, kind)
    path.write_bytes(path.read_bytes() + b"changed bytes")
    with pytest.raises(artifacts.ArtifactError, match=kind + " hash"):
        artifacts.verify(release.evidence, release.directory, COMMIT)


def test_modified_evidence_source_commit_is_rejected(release):
    record(release)
    with pytest.raises(artifacts.ArtifactError, match="source commit"):
        artifacts.verify(release.evidence, release.directory, "d" * 40)


@pytest.mark.parametrize(
    "name", ["../escape.whl", "/tmp/escape.whl", "..", "directory\\escape.whl"]
)
def test_evidence_cannot_select_paths_outside_artifact_directory(release, name):
    evidence = record(release)
    evidence["wheel"]["name"] = name
    release.evidence.write_bytes(encode(evidence))
    with pytest.raises(artifacts.ArtifactError, match="plain filename"):
        artifacts.verify(release.evidence, release.directory, COMMIT)


def test_stale_distribution_files_are_rejected(release):
    (release.directory / "stale.whl").write_bytes(b"old artifact")
    with pytest.raises(artifacts.ArtifactError, match="artifact set"):
        record(release)


def test_symlinked_distribution_files_are_rejected(release):
    content = release.wheel.read_bytes()
    release.wheel.unlink()
    target = release.directory / "outside.bin"
    target.write_bytes(content)
    release.wheel.symlink_to(target)
    with pytest.raises(artifacts.ArtifactError, match="symbolic links"):
        record(release)


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_distribution_metadata_versions_must_agree(release, kind):
    if kind == "wheel":
        release.wheel_files[f"trame_vtkjs-{release.version}.dist-info/METADATA"] = (
            package_metadata("0.2.4")
        )
        write_wheel(release)
    else:
        release.sdist_files[release.prefix + "PKG-INFO"] = package_metadata("0.2.4")
        write_sdist(release)
    with pytest.raises(artifacts.ArtifactError, match="version"):
        record(release)


@pytest.mark.parametrize(
    "name", [artifacts.UMD, "trame/widgets/vtkjs.py", "trame_vtkjs/py.typed"]
)
def test_runtime_asset_or_python_facade_differences_are_rejected(release, name):
    release.sdist_files[release.prefix + "src/" + name] = b"different runtime"
    write_sdist(release)
    with pytest.raises(artifacts.ArtifactError, match="runtime files differ"):
        record(release)


def test_missing_codec_in_both_distributions_is_rejected(release):
    name = "trame_vtkjs/module/serve/wasm/tiles3d/basis_encoder.wasm"
    release.wheel_files.pop(name)
    release.sdist_files.pop(release.prefix + "src/" + name)
    write_wheel(release)
    write_sdist(release)
    with pytest.raises(artifacts.ArtifactError, match="missing runtime files"):
        record(release)


def test_matching_but_unqualified_bundle_bytes_are_rejected(release):
    release.wheel_files[artifacts.UMD] = b"unqualified UMD"
    release.sdist_files[release.prefix + "src/" + artifacts.UMD] = b"unqualified UMD"
    write_wheel(release)
    write_sdist(release)
    with pytest.raises(artifacts.ArtifactError, match="bundle hash"):
        record(release)


def test_build_metadata_must_be_embedded_byte_for_byte(release):
    changed = json.dumps(release.info).encode()
    release.wheel_files[artifacts.BUILD_INFO] = changed
    release.sdist_files[release.prefix + "src/" + artifacts.BUILD_INFO] = changed
    write_wheel(release)
    write_sdist(release)
    with pytest.raises(
        artifacts.ArtifactError, match="exact provided build metadata bytes"
    ):
        record(release)


def test_archive_members_cannot_traverse_outside_the_package(release):
    release.sdist_files[release.prefix + "../escape.py"] = b"unsafe"
    write_sdist(release)
    with pytest.raises(artifacts.ArtifactError, match="unsafe archive member"):
        record(release)


def test_cli_records_and_verifies_json_without_rebuilding(release):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "release_artifacts.py"),
            "record",
            "--wheel",
            str(release.wheel),
            "--sdist",
            str(release.sdist),
            "--build-info",
            str(release.build_info),
            "--commit",
            COMMIT,
            "--tag",
            "trame-vtkjs-v0.2.3",
            "--version",
            "0.2.3",
            "--output",
            str(release.evidence),
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    recorded = json.loads(result.stdout)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "release_artifacts.py"),
            "verify",
            "--evidence",
            str(release.evidence),
            "--artifacts",
            str(release.directory),
            "--commit",
            COMMIT,
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout) == recorded
