"""Stage only missing, verified distributions for an immutable PyPI release."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile


class PreflightError(RuntimeError):
    pass


STABLE_VERSION = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z"
)
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
PROJECT = "trame-vtkjs"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_metadata(content: bytes, version: str, filename: str) -> None:
    metadata = BytesParser().parsebytes(content)
    names = metadata.get_all("Name", [])
    versions = metadata.get_all("Version", [])
    if len(names) != 1 or re.sub(r"[-_.]+", "-", names[0]).lower() != PROJECT:
        raise PreflightError(f"{filename} has an unexpected project name")
    if versions != [version]:
        raise PreflightError(f"{filename} metadata version does not match {version}")


def check_distribution(path: Path, kind: str, version: str) -> None:
    if kind == "wheel":
        metadata_path = f"trame_vtkjs-{version}.dist-info/METADATA"
        with ZipFile(path) as archive:
            entries = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            if entries != [metadata_path]:
                raise PreflightError(f"{path.name} has unexpected wheel metadata")
            check_metadata(archive.read(metadata_path), version, path.name)
    else:
        metadata_path = f"trame_vtkjs-{version}/PKG-INFO"
        with tarfile.open(path, "r:gz") as archive:
            entries = [
                entry
                for entry in archive.getmembers()
                if entry.name.endswith("/PKG-INFO")
            ]
            if (
                len(entries) != 1
                or entries[0].name != metadata_path
                or not entries[0].isfile()
            ):
                raise PreflightError(f"{path.name} has unexpected sdist metadata")
            content = archive.extractfile(entries[0])
            if content is None:
                raise PreflightError(f"{path.name} has no readable sdist metadata")
            with content:
                check_metadata(content.read(), version, path.name)


def candidates(evidence: Path, artifacts: Path) -> tuple[str, dict[str, str]]:
    recorded = json.loads(evidence.read_text())
    if not isinstance(recorded, dict):
        raise PreflightError("release evidence must be an object")
    wheel, sdist = recorded.get("wheel"), recorded.get("sdist")
    if not isinstance(wheel, dict) or not isinstance(sdist, dict):
        raise PreflightError("release evidence must describe both wheel and sdist")
    version = wheel.get("version")
    if not isinstance(version, str) or STABLE_VERSION.fullmatch(version) is None:
        raise PreflightError("PyPI publication requires a stable X.Y.Z version")
    if sdist.get("version") != version:
        raise PreflightError("wheel and sdist evidence versions differ")
    expected = {
        "wheel": f"trame_vtkjs-{version}-py3-none-any.whl",
        "sdist": f"trame_vtkjs-{version}.tar.gz",
    }
    digests = {}
    for kind, name in expected.items():
        entry = recorded[kind]
        digest = entry.get("sha256")
        if entry.get("name") != name:
            raise PreflightError(f"unexpected {kind} distribution filename")
        if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
            raise PreflightError(f"invalid {kind} evidence SHA256")
        path = artifacts / name
        if path.is_symlink() or not path.is_file():
            raise PreflightError(f"missing or symlinked distribution {name}")
        if sha256(path) != digest:
            raise PreflightError(f"{name} differs from the tested release evidence")
        check_distribution(path, kind, version)
        digests[name] = digest
    allowed = {*digests, evidence.name, "release-plan.json"}
    if any(
        path.name not in allowed or not path.is_file() for path in artifacts.iterdir()
    ):
        raise PreflightError("artifact directory contains unexpected release files")
    return version, digests


def fetch_release(version: str) -> object | None:
    request = Request(
        f"https://pypi.org/pypi/{PROJECT}/{version}/json",
        headers={"Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            release = json.load(response)
            if not isinstance(release, dict):
                raise PreflightError("malformed PyPI release response")
            return release
    except HTTPError as error:
        if error.code == 404:
            return None
        raise PreflightError(
            f"PyPI release lookup failed: HTTP {error.code}"
        ) from error
    except (URLError, OSError, ValueError) as error:
        raise PreflightError(f"PyPI release lookup failed: {error}") from error


def missing_files(
    release: object | None, version: str, digests: dict[str, str]
) -> list[str]:
    if release is None:
        return list(digests)
    if not isinstance(release, dict) or not isinstance(release.get("info"), dict):
        raise PreflightError("malformed PyPI release response")
    info = release["info"]
    name = info.get("name")
    if not isinstance(name, str) or re.sub(r"[-_.]+", "-", name).lower() != PROJECT:
        raise PreflightError("PyPI response describes another project")
    if info.get("version") != version or not isinstance(release.get("urls"), list):
        raise PreflightError("PyPI response has an unexpected version or file list")
    published = {}
    for asset in release["urls"]:
        if not isinstance(asset, dict):
            raise PreflightError("malformed PyPI file record")
        filename = asset.get("filename")
        if (
            not isinstance(filename, str)
            or filename not in digests
            or filename in published
        ):
            raise PreflightError(
                "PyPI version contains unexpected or duplicate distribution filenames"
            )
        hashes = asset.get("digests")
        digest = hashes.get("sha256") if isinstance(hashes, dict) else None
        if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
            raise PreflightError(f"PyPI has no valid SHA256 for {filename}")
        if digest != digests[filename]:
            raise PreflightError(
                f"PyPI already contains {filename} with different bytes; publish a new version instead"
            )
        published[filename] = digest
    return [name for name in digests if name not in published]


def stage(evidence: Path, artifacts: Path, output: Path) -> dict:
    artifacts = artifacts.resolve()
    resolved_output = output.resolve()
    if (
        output.is_symlink()
        or resolved_output == artifacts
        or artifacts in resolved_output.parents
    ):
        raise PreflightError("upload directory must be separate from release artifacts")
    if resolved_output in artifacts.parents:
        raise PreflightError("upload directory must not contain release artifacts")
    version, digests = candidates(evidence, artifacts)
    missing = missing_files(fetch_release(version), version, digests)
    existing = list(output.iterdir()) if output.exists() else []
    if any(
        path.name not in digests
        or path.is_symlink()
        or not path.is_file()
        or sha256(path) != digests[path.name]
        for path in existing
    ):
        raise PreflightError("upload directory contains stale or unverified files")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="pypi-stage-", dir=output.parent
    ) as directory:
        temporary = Path(directory)
        for name in missing:
            shutil.copyfile(artifacts / name, temporary / name)
            if sha256(temporary / name) != digests[name]:
                raise PreflightError(f"{name} changed while staging")
        output.mkdir(exist_ok=True)
        for path in existing:
            path.unlink()
        for name in missing:
            (temporary / name).replace(output / name)
    return {"upload": bool(missing), "version": version, "files": missing}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        result = stage(args.evidence, args.artifacts, args.output)
        if args.github_output:
            with args.github_output.open("a") as stream:
                stream.write(f"upload={str(result['upload']).lower()}\n")
    except (PreflightError, OSError, ValueError, BadZipFile, tarfile.TarError) as error:
        sys.exit(f"pypi_assets: ERROR: {error}")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
