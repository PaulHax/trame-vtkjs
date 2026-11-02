import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from git import Repo

spec = importlib.util.spec_from_file_location(
    "release_plan", Path(__file__).resolve().parents[1] / "release_plan.py"
)
release_plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_plan)


@pytest.fixture
def history(tmp_path):
    repo = Repo.init(tmp_path, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "test@example.test")
        config.set_value("commit", "gpgsign", "false")
    baseline = repo.index.commit("feat: historical product")
    (tmp_path / "pyproject.toml").write_text(
        "[tool.semantic_release]\n"
        'commit_parser = "conventional"\n'
        'tag_format = "trame-vtkjs-v{version}"\n'
        "major_on_zero = false\n"
        "allow_zero_version = true\n"
        "[tool.trame_vtkjs.release]\n"
        'initial_version = "0.1.0"\n'
        f'baseline_commit = "{baseline.hexsha}"\n'
    )
    (tmp_path / ".gitignore").write_text("dist/\n")
    repo.index.add(["pyproject.toml", ".gitignore"])
    repo.index.commit("chore: establish product release settings")
    yield tmp_path, repo, baseline
    repo.close()


@pytest.mark.parametrize(
    "message", ["feat: add scene export", "fix: restore worker loading"]
)
def test_first_release_is_independent_0_1_0(history, message):
    root, repo, baseline = history
    repo.create_tag("v0.16.0-shared-context.62ffc67", ref=baseline)
    repo.create_tag("v1.8.1", ref=baseline)
    commit = repo.index.commit(message)
    refs_before = [reference.path for reference in repo.references]
    result = release_plan.plan(root)
    assert result == {
        "commit": commit.hexsha,
        "tree": commit.tree.hexsha,
        "release": True,
        "version": "0.1.0",
        "tag": "trame-vtkjs-v0.1.0",
        "previousTag": None,
        "previousCommit": None,
    }
    assert [reference.path for reference in repo.references] == refs_before
    assert not repo.is_dirty(untracked_files=True)


def test_historical_features_do_not_release_a_docs_only_bootstrap(history):
    root, repo, _ = history
    repo.index.commit("docs: clarify view ownership")
    result = release_plan.plan(root)
    assert result["release"] is False
    assert result["version"] == result["tag"] == ""


@pytest.mark.parametrize(
    ("message", "previous", "expected"),
    [
        ("feat(view): add capture", "0.1.0", "0.2.0"),
        ("fix: repair asset route", "0.1.0", "0.1.1"),
        ("perf: reduce transfer cost", "0.1.0", "0.1.1"),
        ("feat!: replace transport", "0.1.0", "0.2.0"),
        (
            "fix: replace transport\n\nBREAKING CHANGE: use the new message schema",
            "0.1.0",
            "0.2.0",
        ),
        ("feat!: replace transport", "1.2.3", "2.0.0"),
    ],
)
def test_semantic_version_uses_conventional_commits(
    history, message, previous, expected
):
    root, repo, _ = history
    previous_commit = repo.index.commit("feat: initial bridge")
    tag = repo.create_tag(f"trame-vtkjs-v{previous}")
    repo.index.commit(message)
    result = release_plan.plan(root)
    assert result["version"] == expected
    assert result["previousTag"] == tag.name
    assert result["previousCommit"] == previous_commit.hexsha


@pytest.mark.parametrize(
    "kind", ["docs", "chore", "ci", "test", "refactor", "build", "style"]
)
def test_non_release_commits_keep_validation_without_publication(history, kind):
    root, repo, _ = history
    repo.index.commit("feat: initial bridge")
    repo.create_tag("trame-vtkjs-v0.1.0")
    repo.index.commit(f"{kind}: maintain the project")
    result = release_plan.plan(root)
    assert result["release"] is False
    assert result["previousTag"] == "trame-vtkjs-v0.1.0"


def test_tagged_head_is_an_idempotent_retry_of_original_plan(history):
    root, repo, _ = history
    repo.index.commit("feat: initial bridge")
    original = release_plan.plan(root)
    repo.create_tag(original["tag"])
    assert release_plan.plan(root) == original
    release_plan.check(root, original)


def test_tagged_head_retry_retains_previous_release(history):
    root, repo, _ = history
    repo.index.commit("feat: initial bridge")
    repo.create_tag("trame-vtkjs-v0.1.0")
    repo.index.commit("fix: repair texture loading")
    original = release_plan.plan(root)
    repo.create_tag(original["tag"])
    assert release_plan.plan(root) == original


def test_new_release_tag_on_ancestor_invalidates_built_plan(history):
    root, repo, _ = history
    candidate = repo.index.commit("feat: initial bridge")
    repo.index.commit("fix: repair texture loading")
    original = release_plan.plan(root)
    repo.create_tag("trame-vtkjs-v0.1.0", ref=candidate)
    with pytest.raises(release_plan.ReleasePlanError, match="stale release plan"):
        release_plan.check(root, original)


def test_plan_rejects_changed_source_and_dirty_inputs(history):
    root, repo, _ = history
    repo.index.commit("feat: initial bridge")
    original = release_plan.plan(root)
    repo.index.commit("docs: clarify installation")
    with pytest.raises(release_plan.ReleasePlanError, match="stale release plan"):
        release_plan.check(root, original)
    (root / "uncommitted.py").write_text("value = 1\n")
    with pytest.raises(release_plan.ReleasePlanError, match="committed source"):
        release_plan.plan(root)


def test_conflicting_version_on_another_branch_cannot_be_reused(history):
    root, repo, _ = history
    branch_point = repo.head.commit
    other = repo.create_head("other")
    other.checkout()
    repo.index.commit("feat: other source")
    repo.create_tag("trame-vtkjs-v0.1.0")
    repo.heads.main.checkout()
    assert repo.head.commit == branch_point
    repo.index.commit("feat: candidate source")
    with pytest.raises(release_plan.ReleasePlanError, match="another source commit"):
        release_plan.plan(root)


def test_detached_checkout_produces_same_plan_without_creating_a_branch(history):
    root, repo, _ = history
    commit = repo.index.commit("feat: initial bridge")
    original = release_plan.plan(root)
    repo.git.checkout("--detach", commit.hexsha)
    assert release_plan.plan(root) == original
    assert repo.head.is_detached


@pytest.mark.parametrize(
    "message",
    [
        "Fix asset route",
        "feature: add capture",
        "fix: ",
        "fix:\nrepair route",
        "fix(): repair route",
    ],
)
def test_lint_rejects_invalid_commit_messages(history, message):
    root, repo, baseline = history
    repo.index.commit(message)
    with pytest.raises(release_plan.ReleasePlanError, match="invalid commit messages"):
        release_plan.lint_commits(root, baseline.hexsha)


def test_lint_checks_every_landed_commit_not_only_the_tip(history):
    root, repo, baseline = history
    invalid = repo.index.commit("Repair asset route")
    repo.index.commit("feat: add capture")
    with pytest.raises(release_plan.ReleasePlanError, match=invalid.hexsha[:7]):
        release_plan.lint_commits(root, baseline.hexsha)


def test_lint_accepts_scopes_and_breaking_change_footers(history):
    root, repo, baseline = history
    repo.index.commit("fix(worker): load codecs")
    repo.index.commit(
        "feat!: replace transport\n\nBREAKING CHANGE: change the wire schema"
    )
    assert release_plan.lint_commits(root, baseline.hexsha) == 3


def test_initial_pr_grandfathers_baseline_and_older_messages(history):
    root, repo, shipping = history
    baseline = repo.index.commit("Establish independent product identity")
    path = root / "pyproject.toml"
    path.write_text(path.read_text().replace(shipping.hexsha, baseline.hexsha))
    repo.index.add(["pyproject.toml"])
    repo.index.commit("feat: configure public releases")
    assert release_plan.lint_commits(root, shipping.hexsha) == 1


def test_lint_accepts_pr_branch_behind_main_but_checks_its_new_commits(history):
    root, repo, _ = history
    branch = repo.create_head("feature")
    target_head = repo.index.commit("docs: update main documentation")
    branch.checkout()
    repo.index.commit("fix: restore worker loading")
    assert release_plan.lint_commits(root, target_head.hexsha) == 1
    repo.index.commit("Unstructured message")
    with pytest.raises(release_plan.ReleasePlanError, match="invalid commit messages"):
        release_plan.lint_commits(root, target_head.hexsha)


def test_lint_rejects_an_unrelated_base(history, tmp_path):
    root, repo, _ = history
    unrelated = Repo.init(tmp_path / "unrelated", initial_branch="main")
    with unrelated.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "test@example.test")
    commit = unrelated.index.commit("chore: unrelated root")
    repo.git.fetch(str(unrelated.working_tree_dir), commit.hexsha)
    with pytest.raises(release_plan.ReleasePlanError, match="unrelated history"):
        release_plan.lint_commits(root, commit.hexsha)
    unrelated.close()


def test_parser_options_are_shared_by_lint_and_release_planning(history):
    root, repo, baseline = history
    path = root / "pyproject.toml"
    with path.open("a") as stream:
        stream.write(
            "\n[tool.semantic_release.commit_parser_options]\n"
            'allowed_tags = ["feature", "fix", "chore", "revert"]\n'
            'minor_tags = ["feature"]\n'
        )
    repo.index.add(["pyproject.toml"])
    repo.index.commit("chore: configure commit types")
    repo.index.commit("revert: undo an unused setting")
    assert release_plan.plan(root)["release"] is False
    repo.index.commit("feature: add capture")
    assert release_plan.lint_commits(root, baseline.hexsha) == 4
    assert release_plan.plan(root)["version"] == "0.1.0"


def test_cli_writes_plan_outputs_and_checks_same_artifact(history):
    root, repo, _ = history
    repo.index.commit("feat: initial bridge")
    output = root / "dist/plan.json"
    github_output = root / "dist/outputs"
    result = subprocess.run(
        [
            sys.executable,
            str(Path(release_plan.__file__)),
            "plan",
            "--output",
            str(output),
            "--github-output",
            str(github_output),
        ],
        cwd=root,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())["version"] == "0.1.0"
    assert (
        github_output.read_text()
        == "release=true\nversion=0.1.0\ntag=trame-vtkjs-v0.1.0\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(Path(release_plan.__file__)),
            "check",
            "--plan",
            str(output),
        ],
        cwd=root,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
