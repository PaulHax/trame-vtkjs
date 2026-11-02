"""Record and verify the exact wheel and source distribution qualified for release."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
from zipfile import BadZipFile, ZipFile


class ArtifactError(RuntimeError):
    pass


PUBLIC_VERSION = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z"
)
DEVELOPMENT_VERSION = re.compile(
    r"((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))\+git\.([0-9a-f]{7,40})\Z"
)
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
BUILD_INFO = "trame_vtkjs/module/serve/js/build-info.json"
UMD = "trame_vtkjs/module/serve/js/trame_vtkjs.umd.js"
REQUIRED_RUNTIME = frozenset(
    {
        "trame_vtkjs/__init__.py",
        "trame_vtkjs/py.typed",
        "trame/modules/vtkjs.py",
        "trame/widgets/vtkjs.py",
        BUILD_INFO,
        UMD,
        "trame_vtkjs/module/serve/js/tiles3dDecodeWorker.classic.js",
        "trame_vtkjs/module/serve/wasm/tiles3d/draco_wasm_wrapper.js",
        "trame_vtkjs/module/serve/wasm/tiles3d/draco_decoder.wasm",
        "trame_vtkjs/module/serve/wasm/tiles3d/basis_encoder.js",
        "trame_vtkjs/module/serve/wasm/tiles3d/basis_encoder.wasm",
    }
)


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256(path: Path) -> str:
    return digest(path.read_bytes())


def json_object(content: bytes, label: str) -> dict:
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ArtifactError(f"{label} must contain a JSON object")
    return value


def expected_tag(version: str, commit: str) -> str:
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        raise ArtifactError("source commit must be a full Git revision")
    if not isinstance(version, str):
        raise ArtifactError("package version must be a string")
    if PUBLIC_VERSION.fullmatch(version):
        return f"trame-vtkjs-v{version}"
    development = DEVELOPMENT_VERSION.fullmatch(version)
    if development and commit.startswith(development[2]):
        return f"v{development[1]}-git.{development[2]}"
    raise ArtifactError(
        "version must be public X.Y.Z or a development version naming the source commit"
    )


def metadata(content: bytes, label: str) -> str:
    value = BytesParser().parsebytes(content)
    names = value.get_all("Name", [])
    versions = value.get_all("Version", [])
    if len(names) != 1 or re.sub(r"[-_.]+", "-", names[0]).lower() != "trame-vtkjs":
        raise ArtifactError(f"{label} does not identify the trame-vtkjs distribution")
    if len(versions) != 1:
        raise ArtifactError(f"{label} must contain exactly one package version")
    return versions[0]


def safe_member(name: str) -> None:
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != name.rstrip("/")
    ):
        raise ArtifactError(f"unsafe archive member: {name!r}")


def wheel_contents(path: Path) -> tuple[str, dict[str, bytes]]:
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ArtifactError("wheel contains duplicate archive members")
        for item in archive.infolist():
            safe_member(item.filename)
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ArtifactError("wheel contains a symbolic link")
        candidates = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(candidates) != 1:
            raise ArtifactError("wheel must contain exactly one package metadata file")
        version = metadata(archive.read(candidates[0]), "wheel metadata")
        if candidates[0] != f"trame_vtkjs-{version}.dist-info/METADATA":
            raise ArtifactError("wheel metadata path does not match its version")
        runtime = {
            name: archive.read(name)
            for name in names
            if name.startswith(("trame_vtkjs/", "trame/")) and not name.endswith("/")
        }
    return version, runtime


def sdist_contents(path: Path, version: str) -> tuple[str, dict[str, bytes]]:
    prefix = f"trame_vtkjs-{version}/"
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise ArtifactError("sdist contains duplicate archive members")
        for member in members:
            safe_member(member.name)
            if not member.name.startswith(prefix) and member.name != prefix.rstrip("/"):
                raise ArtifactError(
                    "sdist members must share the canonical package root"
                )
            if not member.isfile() and not member.isdir():
                raise ArtifactError("sdist contains a nonregular archive member")
        candidates = [name for name in names if name.endswith("/PKG-INFO")]
        if candidates != [prefix + "PKG-INFO"]:
            raise ArtifactError(
                "sdist must contain exactly one root package metadata file"
            )
        archived_version = metadata(
            archive.extractfile(candidates[0]).read(), "sdist metadata"
        )
        for required in ("hatch_build.py", "pyproject.toml", "README.md", "LICENSE"):
            if prefix + required not in names:
                raise ArtifactError(f"sdist is missing {required}")
        source_prefix = prefix + "src/"
        runtime = {
            member.name.removeprefix(source_prefix): archive.extractfile(member).read()
            for member in members
            if member.isfile()
            and member.name.startswith(
                (source_prefix + "trame_vtkjs/", source_prefix + "trame/")
            )
        }
    return archived_version, runtime


def check_source(build_info: dict, commit: str) -> None:
    source = build_info.get("bridgeSource", {})
    if not isinstance(source, dict):
        raise ArtifactError("build metadata is missing source provenance")
    if build_info.get("bridgeCommit") != commit or source.get("commit") != commit:
        raise ArtifactError(
            "build metadata source commit does not match the expected commit"
        )
    if source.get("dirty") is not False:
        raise ArtifactError("build metadata does not identify clean source")
    tree = source.get("tree", "")
    if not isinstance(tree, str) or not COMMIT.fullmatch(tree):
        raise ArtifactError("build metadata must identify the source tree")


def check_artifact_set(directory: Path, wheel_name: str, sdist_name: str) -> None:
    actual = {
        path.name
        for path in directory.iterdir()
        if path.name.endswith((".whl", ".tar.gz"))
    }
    if actual != {wheel_name, sdist_name}:
        raise ArtifactError(
            "expected exactly the recorded wheel and sdist artifact set"
        )
    if any(
        not (directory / name).is_file() or (directory / name).is_symlink()
        for name in actual
    ):
        raise ArtifactError(
            "release artifacts must be regular files, not symbolic links"
        )


def check_distributions(
    wheel: Path, sdist: Path, build_info: dict, commit: str, tag: str
) -> str:
    version, wheel_runtime = wheel_contents(wheel)
    if wheel.name != f"trame_vtkjs-{version}-py3-none-any.whl":
        raise ArtifactError(
            "wheel filename does not match the canonical package version"
        )
    if sdist.name != f"trame_vtkjs-{version}.tar.gz":
        raise ArtifactError(
            "sdist filename does not match the canonical package version"
        )
    if tag != expected_tag(version, commit):
        raise ArtifactError(
            "release tag does not match the package version and source commit"
        )
    archived_version, sdist_runtime = sdist_contents(sdist, version)
    if archived_version != version:
        raise ArtifactError("wheel and sdist package versions differ")
    missing = REQUIRED_RUNTIME.difference(wheel_runtime)
    if missing:
        raise ArtifactError(
            f"wheel is missing runtime files: {', '.join(sorted(missing))}"
        )
    if wheel_runtime != sdist_runtime:
        raise ArtifactError("wheel and sdist runtime files differ")
    embedded = json_object(wheel_runtime[BUILD_INFO], "embedded build metadata")
    if embedded != build_info:
        raise ArtifactError(
            "wheel build metadata differs from the recorded build metadata"
        )
    check_source(embedded, commit)
    bundle = embedded.get("bundle", {})
    if not isinstance(bundle, dict) or bundle.get("sha256") != digest(
        wheel_runtime[UMD]
    ):
        raise ArtifactError("wheel UMD does not match the recorded bundle hash")
    if "bytes" in bundle and bundle["bytes"] != len(wheel_runtime[UMD]):
        raise ArtifactError("wheel UMD does not match the recorded bundle size")
    return version


def record(
    wheel: Path,
    sdist: Path,
    build_info: Path,
    commit: str,
    tag: str,
    output: Path,
    version: str | None = None,
) -> dict:
    if wheel.parent.resolve() != sdist.parent.resolve():
        raise ArtifactError("wheel and sdist must share an artifact directory")
    check_artifact_set(wheel.parent, wheel.name, sdist.name)
    raw_build_info = build_info.read_bytes()
    evidence = json_object(raw_build_info, "build metadata")
    if "wheel" in evidence or "sdist" in evidence:
        raise ArtifactError("build metadata must not contain distribution evidence")
    actual_version = check_distributions(wheel, sdist, evidence, commit, tag)
    if version is not None:
        if not PUBLIC_VERSION.fullmatch(version) or version != actual_version:
            raise ArtifactError(
                "requested public version does not match the package version"
            )
    elif not DEVELOPMENT_VERSION.fullmatch(actual_version):
        raise ArtifactError("recording a public release requires --version")
    with ZipFile(wheel) as archive:
        if archive.read(BUILD_INFO) != raw_build_info:
            raise ArtifactError(
                "wheel must embed the exact provided build metadata bytes"
            )
    evidence["wheel"] = {
        "name": wheel.name,
        "sha256": sha256(wheel),
        "version": actual_version,
        "tag": tag,
    }
    evidence["sdist"] = {
        "name": sdist.name,
        "sha256": sha256(sdist),
        "version": actual_version,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return evidence


def evidence_filename(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "\\" in value
        or PurePosixPath(value).name != value
    ):
        raise ArtifactError("evidence artifact name must be a plain filename")
    return value


def verify(evidence_path: Path, artifacts: Path, commit: str) -> dict:
    evidence = json_object(evidence_path.read_bytes(), "release evidence")
    entries = {}
    for kind in ("wheel", "sdist"):
        entry = evidence.get(kind)
        if not isinstance(entry, dict):
            raise ArtifactError(f"release evidence is missing {kind}")
        name = evidence_filename(entry.get("name"))
        recorded_digest = entry.get("sha256", "")
        if not isinstance(recorded_digest, str) or not DIGEST.fullmatch(
            recorded_digest
        ):
            raise ArtifactError(f"release evidence has an invalid {kind} hash")
        entries[kind] = (entry, artifacts / name)
    check_artifact_set(artifacts, entries["wheel"][1].name, entries["sdist"][1].name)
    for kind, (entry, path) in entries.items():
        if sha256(path) != entry["sha256"]:
            raise ArtifactError(f"{kind} hash does not match release evidence")
    build_info = {
        key: value for key, value in evidence.items() if key not in {"wheel", "sdist"}
    }
    version = check_distributions(
        entries["wheel"][1],
        entries["sdist"][1],
        build_info,
        commit,
        entries["wheel"][0].get("tag"),
    )
    if any(entry.get("version") != version for entry, _ in entries.values()):
        raise ArtifactError(
            "distribution evidence versions do not match the package version"
        )
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    recording = commands.add_parser("record")
    for name in ("wheel", "sdist", "build-info", "output"):
        recording.add_argument(f"--{name}", required=True, type=Path)
    recording.add_argument("--commit", required=True)
    recording.add_argument("--tag", required=True)
    recording.add_argument("--version")
    checking = commands.add_parser("verify")
    checking.add_argument("--evidence", required=True, type=Path)
    checking.add_argument("--artifacts", required=True, type=Path)
    checking.add_argument("--commit", required=True)
    args = parser.parse_args()
    try:
        if args.command == "record":
            result = record(
                args.wheel,
                args.sdist,
                args.build_info,
                args.commit,
                args.tag,
                args.output,
                args.version,
            )
        else:
            result = verify(args.evidence, args.artifacts, args.commit)
    except (ArtifactError, BadZipFile, tarfile.TarError, OSError, ValueError) as error:
        sys.exit(f"release_artifacts: ERROR: {error}")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
