"""Verify the pinned local Gaussian snapshot without relaxing release verification."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import tarfile
from pathlib import Path

from verify_chain import (
    ROOT,
    VUE,
    bridge_source,
    check_adaptive_floor,
    check_bundle,
    check_no_vtkjs_range,
    check_vtkjs,
    git_output,
    read_pin,
)


def verify_snapshot(source: Path) -> dict:
    pin = json.loads((ROOT / "local-dependencies/tiled-vtkjs-source.json").read_text())
    revision = git_output(source, "rev-parse", "HEAD")
    if revision != pin["sourceRevision"] or git_output(source, "status", "--porcelain"):
        raise ValueError(
            "tiled-vtkjs source must be clean and at the recorded immutable revision"
        )
    archive = ROOT / pin["archive"]
    integrity = (
        "sha512-"
        + base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()
    )
    if integrity != pin["integrity"]:
        raise ValueError("local tiled-vtkjs archive integrity mismatch")
    manifest = json.loads((VUE / "package.json").read_text())
    lock = json.loads((VUE / "package-lock.json").read_text())
    if manifest["dependencies"]["tiled-vtkjs"] != pin["specifier"]:
        raise ValueError("package manifest does not name the recorded local snapshot")
    entry = lock["packages"]["node_modules/tiled-vtkjs"]
    if entry.get("integrity") != integrity or entry.get("resolved") != pin["specifier"]:
        raise ValueError("package lock does not bind the local archive bytes")
    installed = VUE / "node_modules/tiled-vtkjs"
    if installed.is_symlink():
        raise ValueError(
            "install the immutable snapshot rather than linking a working copy"
        )
    with tarfile.open(archive) as packed:
        for member in packed.getmembers():
            if not member.isfile():
                continue
            relative = Path(member.name).relative_to("package")
            if ".." in relative.parts:
                raise ValueError("invalid archive path")
            stream = packed.extractfile(member)
            if stream is None or (installed / relative).read_bytes() != stream.read():
                raise ValueError(f"installed snapshot differs from archive: {relative}")
    return {
        **pin,
        "version": json.loads((installed / "package.json").read_text())["version"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tiled-source", type=Path, required=True)
    args = parser.parse_args()
    tiled = verify_snapshot(args.tiled_source.resolve())
    vtkjs = check_vtkjs(read_pin())
    check_no_vtkjs_range()
    umd = ROOT / "src/trame_vtkjs/module/serve/js/trame_vtkjs.umd.js"
    build_info = {
        "localOnly": True,
        "bridgeCommit": git_output(ROOT, "rev-parse", "HEAD"),
        "bridgeSource": bridge_source(),
        "vtkjs": vtkjs,
        "tiledVtkjs": {**tiled, **check_adaptive_floor()},
        "bundle": check_bundle(umd),
    }
    (umd.parent / "build-info.json").write_text(json.dumps(build_info, indent=2) + "\n")
    print(json.dumps(build_info, indent=2))


if __name__ == "__main__":
    main()
