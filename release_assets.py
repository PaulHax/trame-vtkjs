"""Publish immutable GitHub release assets after comparing existing bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote


class ReleaseError(RuntimeError):
    pass


def gh(*args: str, missing_ok: bool = False) -> str | None:
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode:
        if missing_ok and "(HTTP 404)" in result.stderr:
            return None
        raise ReleaseError(result.stderr.strip() or f"gh {' '.join(args)} failed")
    return result.stdout


def api(path: str, *, missing_ok: bool = False):
    value = gh("api", "--hostname", "github.com", path, missing_ok=missing_ok)
    return None if value is None else json.loads(value)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def matching_asset(assets: list[dict], path: Path) -> dict | None:
    # GitHub may replace '+' in a PEP 440 wheel filename with '.'.
    candidates = {path.name, path.name.replace("+", ".")}
    matches = [asset for asset in assets if asset["name"] in candidates]
    if len(matches) > 1:
        raise ReleaseError(f"ambiguous existing assets for {path.name}")
    return matches[0] if matches else None


def verify_assets(
    repository: str, tag: str, assets: list[dict], paths: list[Path]
) -> list[Path]:
    """Check all collisions before uploading any missing files."""
    missing = []
    with tempfile.TemporaryDirectory(prefix="release-assets-") as directory:
        for index, path in enumerate(paths):
            asset = matching_asset(assets, path)
            if asset is None:
                missing.append(path)
                continue
            downloaded = Path(directory) / str(index)
            gh(
                "release",
                "download",
                tag,
                "--repo",
                repository,
                "--pattern",
                asset["name"],
                "--output",
                str(downloaded),
            )
            if sha256(downloaded) != sha256(path):
                raise ReleaseError(
                    f"release {tag} already contains {asset['name']} with different bytes; "
                    "publish a new version instead"
                )
    return missing


def publish(
    repository: str,
    tag: str,
    commit: str,
    notes: Path,
    paths: list[Path],
    *,
    prerelease: bool = True,
) -> dict[str, str]:
    if not paths or len({path.name for path in paths}) != len(paths):
        raise ReleaseError("release asset names must be unique")
    if any(not path.is_file() for path in paths):
        raise ReleaseError("a release input file is missing")
    prefix = f"repos/{repository}"
    encoded_tag = quote(tag, safe="")
    release = api(f"{prefix}/releases/tags/{encoded_tag}", missing_ok=True)
    existing_tag = api(f"{prefix}/git/ref/tags/{encoded_tag}", missing_ok=True)
    existing_commit = api(f"{prefix}/commits/{encoded_tag}") if existing_tag else None
    if existing_commit is not None and existing_commit["sha"] != commit:
        raise ReleaseError(
            f"tag {tag} points to {existing_commit['sha']}, expected {commit}"
        )
    if release is not None:
        if existing_commit is None:
            raise ReleaseError(f"release {tag} has no resolvable source commit")
        if release.get("prerelease", prerelease) != prerelease:
            raise ReleaseError(f"release {tag} has a different prerelease status")
        missing = verify_assets(repository, tag, release["assets"], paths)
        if missing:
            gh(
                "release",
                "upload",
                tag,
                *(str(path) for path in missing),
                "--repo",
                repository,
            )
    else:
        gh(
            "release",
            "create",
            tag,
            *(str(path) for path in paths),
            "--repo",
            repository,
            "--target",
            commit,
            *(["--prerelease"] if prerelease else []),
            "--title",
            tag,
            "--notes-file",
            str(notes),
        )
    published = api(f"{prefix}/releases/tags/{encoded_tag}")
    if verify_assets(repository, tag, published["assets"], paths):
        raise ReleaseError("published release is missing an expected asset")
    return {
        path.name: matching_asset(published["assets"], path)["browser_download_url"]
        for path in paths
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--notes", required=True, type=Path)
    parser.add_argument("--stable", action="store_true")
    parser.add_argument("assets", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        urls = publish(
            args.repository,
            args.tag,
            args.commit,
            args.notes,
            args.assets,
            prerelease=not args.stable,
        )
    except (ReleaseError, OSError, ValueError) as error:
        sys.exit(f"release_assets: ERROR: {error}")
    print(json.dumps(urls))


if __name__ == "__main__":
    main()
