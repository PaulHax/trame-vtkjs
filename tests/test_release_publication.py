"""Run the public shell publisher against isolated Git histories and a fake CLI."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from git import Repo
import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


planner = load_module("publication_planner", ROOT / "release_plan.py")
artifacts = load_module(
    "publication_artifacts", ROOT / "tests/test_release_artifacts.py"
)


@pytest.mark.parametrize(
    ("releasing", "version", "tagged", "allowed"),
    [
        (True, "0.9.0", False, False),
        (False, "0.9.0", False, False),
        (True, "0.1.0", False, True),
        (True, "0.1.0", True, True),
    ],
)
def test_publication_obeys_the_semantic_plan(
    tmp_path, releasing, version, tagged, allowed
):
    source = tmp_path / "source"
    source.mkdir()
    for name in (
        "release.sh",
        "release_plan.py",
        "release_artifacts.py",
        "release_assets.py",
        "hatch_build.py",
        "vtkjs-fork.env",
        "pyproject.toml",
    ):
        shutil.copyfile(ROOT / name, source / name)
    (source / ".gitignore").write_text("dist/\n__pycache__/\n")
    repo = Repo.init(source, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "test@example.test")
        config.set_value("commit", "gpgsign", "false")
    repo.index.add([path.name for path in source.iterdir() if path.is_file()])
    baseline = repo.index.commit("chore: establish source")
    project = source / "pyproject.toml"
    project.write_text(
        project.read_text().replace(planner.BASELINE_COMMIT, baseline.hexsha)
    )
    repo.index.add(["pyproject.toml"])
    repo.index.commit("feat: introduce the product")
    if not releasing:
        repo.create_tag("trame-vtkjs-v0.1.0")
        repo.index.commit("docs: explain the views")
    head = repo.head.commit
    plan = planner.plan(source)
    if tagged:
        repo.create_tag(plan["tag"])
    state = artifacts.make_artifacts(
        source / "dist", version, commit=head.hexsha, tree=head.tree.hexsha
    )
    artifacts.record(state, commit=head.hexsha, tag=f"trame-vtkjs-v{version}")
    (source / "dist/release-plan.json").write_text(json.dumps(plan))

    binary = tmp_path / "bin"
    binary.mkdir()
    calls = tmp_path / "calls.jsonl"
    gh = binary / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "with Path(os.environ['PUBLICATION_CALLS']).open('a') as stream:\n"
        " stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1] == 'api':\n"
        " print('Not Found (HTTP 404)', file=sys.stderr)\n"
        " sys.exit(1)\n"
        "print('intercepted publication', file=sys.stderr)\n"
        "sys.exit(66)\n"
    )
    gh.chmod(0o755)
    result = subprocess.run(
        ["bash", "release.sh", "publish"],
        cwd=source,
        env={
            **os.environ,
            "PYTHON": sys.executable,
            "TRAME_VTKJS_RELEASE_VERSION": version,
            "GH_TOKEN": "test-placeholder",
            "PATH": f"{binary}:{os.environ['PATH']}",
            "PUBLICATION_CALLS": str(calls),
        },
        capture_output=True,
        text=True,
    )
    mutations = (
        [
            call
            for line in calls.read_text().splitlines()
            if (call := json.loads(line))[:2]
            in (["release", "create"], ["release", "upload"])
        ]
        if calls.exists()
        else []
    )
    if allowed:
        assert [call[:3] for call in mutations] == [
            ["release", "create", "trame-vtkjs-v0.1.0"]
        ], result.stderr
        assert "intercepted publication" in result.stderr
    else:
        assert result.returncode != 0
        assert not mutations
        expected = "does not match" if releasing else "does not select a release"
        assert expected in result.stderr
    repo.close()
