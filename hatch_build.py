"""Resolve public release, source distribution and development versions.

Release builds provide ``TRAME_VTKJS_RELEASE_VERSION`` as a public ``X.Y.Z``
version. Source distributions retain that version in ``PKG-INFO`` so installing
them requires neither Git nor a release environment. Development checkouts use
``<BASE_VERSION>+git.<short-sha>``. Exact source provenance lives in the bundled
build metadata for both public and development wheels.
"""

from __future__ import annotations

import os
import re
import subprocess
from email.parser import Parser
from pathlib import Path

from hatchling.metadata.plugin.interface import MetadataHookInterface
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

# Development versions retain a readable base independently of release tags.
BASE_VERSION = "0.1.0"
LOCAL_LABEL = "git"
PUBLIC_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")


def _release_version() -> str | None:
    version = os.environ.get("TRAME_VTKJS_RELEASE_VERSION")
    if version is not None and not PUBLIC_VERSION.fullmatch(version):
        raise ValueError("TRAME_VTKJS_RELEASE_VERSION must be a public X.Y.Z version")
    return version


def _sdist_version(root: str) -> str | None:
    path = Path(root) / "PKG-INFO"
    if not path.is_file():
        return None
    metadata = Parser().parsestr(path.read_text(encoding="utf-8"))
    if canonicalize_name(metadata.get("Name", "")) != "trame-vtkjs":
        raise ValueError("PKG-INFO does not identify the trame-vtkjs distribution")
    version = metadata.get("Version", "")
    try:
        return str(Version(version))
    except InvalidVersion as error:
        raise ValueError("PKG-INFO must contain a valid package version") from error


def _short_sha(root: str) -> str | None:
    sha = os.environ.get("TRAME_VTKJS_SHA")
    if sha:
        return sha.strip()
    try:
        toplevel = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
        if Path(toplevel.decode().strip()).resolve() != Path(root).resolve():
            return None
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.decode().strip() or None


def _stamped_version(root: str) -> str:
    release = _release_version()
    if release is not None:
        return release
    archived = _sdist_version(root)
    if archived is not None:
        return archived
    sha = _short_sha(root)
    if not sha:
        raise ValueError(
            "Package version requires a Git checkout, sdist PKG-INFO, or "
            "TRAME_VTKJS_RELEASE_VERSION"
        )
    return f"{BASE_VERSION}+{LOCAL_LABEL}.{sha}"


class ShaVersionMetadataHook(MetadataHookInterface):
    def update(self, metadata: dict) -> None:
        metadata["version"] = _stamped_version(self.root)
