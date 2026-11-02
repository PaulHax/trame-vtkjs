import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("command", ["build", "publish"])
@pytest.mark.parametrize("change", ["tracked", "untracked"])
def test_release_refuses_uncommitted_source_before_build_or_publication(tmp_path, command, change):
    root = Path(__file__).resolve().parents[1]
    for name in ("release.sh", "vtkjs-fork.env", "hatch_build.py"):
        shutil.copyfile(root / name, tmp_path / name)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.test",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.test",
    }
    for args in (
        ["git", "init", "--quiet"],
        ["git", "add", "."],
        ["git", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Initial release inputs"],
    ):
        subprocess.run(args, cwd=tmp_path, env=env, check=True)
    path = tmp_path / ("hatch_build.py" if change == "tracked" else "uncommitted-source.py")
    with path.open("a") as stream:
        stream.write("\nvalue = 1\n")
    result = subprocess.run(
        ["bash", "release.sh", command], cwd=tmp_path, env=env,
        text=True, capture_output=True,
    )
    assert result.returncode != 0
    assert "commit the release inputs first" in result.stderr
