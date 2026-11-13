"""Build integrity-checked development distributions, never a public release."""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import release_artifacts
import verify_chain as chain


def run(*args: str, cwd: Path = chain.ROOT) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tiled-source", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("TRAME_VTKJS_RELEASE_VERSION") is not None:
        raise ValueError("Review snapshots cannot set a public release version")
    if chain.git_output(chain.ROOT, "status", "--porcelain"):
        raise ValueError("Commit review inputs before building distributions")
    commit = chain.git_output(chain.ROOT, "rev-parse", "HEAD")
    chain.check_vtkjs(chain.read_pin())
    renderer = (chain.VUE / "node_modules/@kitware/vtk.js").resolve()
    run("npm", "ci", cwd=chain.VUE)
    link = chain.VUE / "node_modules/@kitware/vtk.js"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(renderer, target_is_directory=True)
    run("npm", "run", "build", cwd=chain.VUE)
    run(
        sys.executable,
        "verify_local_chain.py",
        "--tiled-source",
        str(args.tiled_source.resolve()),
    )
    dist = chain.ROOT / "dist"
    dist.mkdir(exist_ok=True)
    if list(dist.glob("*.whl")) or list(dist.glob("*.tar.gz")):
        raise ValueError("Use an empty dist directory for a review snapshot")
    run(sys.executable, "-m", "build", "--wheel", "--sdist", "--outdir", str(dist))
    wheels = list(dist.glob("*.whl"))
    sources = list(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("Expected exactly one wheel and source distribution")
    info = chain.ROOT / "src/trame_vtkjs/module/serve/js/build-info.json"
    evidence = release_artifacts.record(
        wheels[0],
        sources[0],
        info,
        commit,
        "v0.1.0-git." + chain.git_output(chain.ROOT, "rev-parse", "--short", "HEAD"),
        dist / "release-evidence.json",
    )
    release_artifacts.verify(dist / "release-evidence.json", dist, commit)
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
