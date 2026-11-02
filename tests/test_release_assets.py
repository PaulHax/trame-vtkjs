import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "release_assets", Path(__file__).resolve().parents[1] / "release_assets.py"
)
release_assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_assets)

REPOSITORY = "owner/product"
COMMIT = "a" * 40
TAG = "v0.1.0-git.abcdef0"


@pytest.fixture
def release(tmp_path, monkeypatch):
    wheel = tmp_path / "trame_vtkjs-0.1.0+git.abcdef0-py3-none-any.whl"
    wheel.write_bytes(b"tested-wheel")
    evidence = tmp_path / "release-evidence.json"
    evidence.write_bytes(b"tested-evidence")
    notes = tmp_path / "notes.txt"
    notes.write_text("Release notes")
    state = SimpleNamespace(
        exists=True, tag_commit=COMMIT, assets={}, mutations=[],
        wheel=wheel, evidence=evidence, notes=notes,
    )

    def published():
        return {"assets": [
            {"name": name, "browser_download_url": f"https://example.test/{name}"}
            for name in state.assets
        ]}

    def fake_api(path, *, missing_ok=False):
        if "/git/ref/tags/" in path:
            return {"object": {"sha": state.tag_commit}} if state.tag_commit else None
        if "/commits/" in path:
            return {"sha": state.tag_commit}
        return published() if state.exists else None

    def fake_gh(*args, **kwargs):
        operation = args[:2]
        if operation == ("release", "download"):
            name = args[args.index("--pattern") + 1]
            Path(args[args.index("--output") + 1]).write_bytes(state.assets[name])
        elif operation in (("release", "upload"), ("release", "create")):
            state.mutations.append(args)
            for item in args[3:args.index("--repo")]:
                path = Path(item)
                state.assets[path.name.replace("+", ".")] = path.read_bytes()
            state.exists = True
        else:
            raise AssertionError(args)
        return ""

    monkeypatch.setattr(release_assets, "api", fake_api)
    monkeypatch.setattr(release_assets, "gh", fake_gh)
    return state


def publish(state):
    return release_assets.publish(
        REPOSITORY, TAG, COMMIT, state.notes, [state.wheel, state.evidence]
    )


def add_existing(state, path, content=None):
    state.assets[path.name.replace("+", ".")] = path.read_bytes() if content is None else content


def test_identical_assets_are_an_idempotent_no_op(release):
    add_existing(release, release.wheel)
    add_existing(release, release.evidence)
    urls = publish(release)
    assert urls[release.wheel.name].endswith(release.wheel.name.replace("+", "."))
    assert release.mutations == []


@pytest.mark.parametrize("changed", ["wheel", "evidence"])
def test_differing_bytes_refuse_all_uploads(release, changed):
    path = getattr(release, changed)
    add_existing(release, path, b"previous-release")
    with pytest.raises(release_assets.ReleaseError, match="different bytes"):
        publish(release)
    assert release.assets == {path.name.replace("+", "."): b"previous-release"}
    assert release.mutations == []


def test_only_missing_assets_are_uploaded(release):
    add_existing(release, release.wheel)
    publish(release)
    assert len(release.mutations) == 1
    assert release.mutations[0][:4] == ("release", "upload", TAG, str(release.evidence))
    assert "--clobber" not in release.mutations[0]


def test_new_release_uses_the_tested_source_commit_and_assets(release):
    release.exists = False
    release.tag_commit = None
    publish(release)
    args = release.mutations[0]
    assert args[:5] == ("release", "create", TAG, str(release.wheel), str(release.evidence))
    assert args[args.index("--target") + 1] == COMMIT
    assert args[args.index("--repo") + 1] == REPOSITORY
    assert args[args.index("--notes-file") + 1] == str(release.notes)


def test_existing_tag_cannot_be_retargeted(release):
    release.tag_commit = "b" * 40
    with pytest.raises(release_assets.ReleaseError, match="points to"):
        publish(release)
    assert release.mutations == []


def test_ambiguous_sanitized_assets_are_rejected(release):
    add_existing(release, release.wheel)
    release.assets[release.wheel.name] = release.wheel.read_bytes()
    with pytest.raises(release_assets.ReleaseError, match="ambiguous"):
        publish(release)
    assert release.mutations == []


def test_api_failures_are_not_treated_as_a_missing_release(monkeypatch):
    monkeypatch.setattr(
        release_assets.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="rate limit (HTTP 403)"),
    )
    with pytest.raises(release_assets.ReleaseError, match="403"):
        release_assets.api("repos/owner/product/releases/tags/v1", missing_ok=True)


def test_missing_api_resource_is_distinct_from_a_failed_lookup(monkeypatch):
    monkeypatch.setattr(
        release_assets.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="Not Found (HTTP 404)"),
    )
    assert release_assets.api("repos/owner/product/releases/tags/v1", missing_ok=True) is None
