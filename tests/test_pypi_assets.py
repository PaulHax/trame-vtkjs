import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tarfile
from urllib.error import HTTPError, URLError
from zipfile import ZipFile

import pytest

spec = importlib.util.spec_from_file_location(
    "pypi_assets", Path(__file__).resolve().parents[1] / "pypi_assets.py"
)
pypi_assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pypi_assets)

VERSION = "0.1.0"
WHEEL = f"trame_vtkjs-{VERSION}-py3-none-any.whl"
SDIST = f"trame_vtkjs-{VERSION}.tar.gz"


def write_wheel(path, *, name="trame-vtkjs", version=VERSION):
    with ZipFile(path, "w") as archive:
        archive.writestr(
            f"trame_vtkjs-{VERSION}.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n",
        )


def write_sdist(path, *, name="trame-vtkjs", version=VERSION):
    content = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n".encode()
    entry = tarfile.TarInfo(f"trame_vtkjs-{VERSION}/PKG-INFO")
    entry.size = len(content)
    with tarfile.open(path, "w:gz") as archive:
        archive.addfile(entry, io.BytesIO(content))


@pytest.fixture
def release(tmp_path, monkeypatch):
    artifacts = tmp_path / "dist"
    artifacts.mkdir()
    write_wheel(artifacts / WHEEL)
    write_sdist(artifacts / SDIST)
    evidence = artifacts / "release-evidence.json"
    record = {
        "wheel": {
            "name": WHEEL,
            "sha256": pypi_assets.sha256(artifacts / WHEEL),
            "version": VERSION,
            "tag": f"trame-vtkjs-v{VERSION}",
        },
        "sdist": {
            "name": SDIST,
            "sha256": pypi_assets.sha256(artifacts / SDIST),
            "version": VERSION,
        },
    }
    evidence.write_text(json.dumps(record))
    state = SimpleNamespace(
        artifacts=artifacts,
        evidence=evidence,
        output=tmp_path / "pypi-dist",
        record=record,
        remote=None,
    )
    monkeypatch.setattr(pypi_assets, "fetch_release", lambda version: state.remote)
    return state


def stage(state):
    return pypi_assets.stage(state.evidence, state.artifacts, state.output)


def published(state, *kinds):
    return {
        "info": {"name": "trame-vtkjs", "version": VERSION},
        "urls": [
            {
                "filename": state.record[kind]["name"],
                "digests": {"sha256": state.record[kind]["sha256"]},
            }
            for kind in kinds
        ],
    }


def save_record(state):
    state.evidence.write_text(json.dumps(state.record))


def test_new_release_stages_exact_tested_wheel_and_sdist(release):
    result = stage(release)
    assert result == {"upload": True, "version": VERSION, "files": [WHEEL, SDIST]}
    assert sorted(path.name for path in release.output.iterdir()) == sorted(
        [WHEEL, SDIST]
    )
    for name in result["files"]:
        assert (release.output / name).read_bytes() == (
            release.artifacts / name
        ).read_bytes()


def test_release_plan_is_retained_as_metadata_and_never_staged(release):
    (release.artifacts / "release-plan.json").write_text(
        json.dumps({"version": VERSION, "tag": f"trame-vtkjs-v{VERSION}"})
    )
    assert stage(release)["files"] == [WHEEL, SDIST]
    assert sorted(path.name for path in release.output.iterdir()) == sorted(
        [WHEEL, SDIST]
    )
    assert (release.artifacts / "release-plan.json").is_file()


def test_identical_existing_release_needs_no_upload(release, monkeypatch):
    release.remote = published(release, "wheel", "sdist")
    monkeypatch.setattr(
        pypi_assets.shutil, "copyfile", lambda *args: pytest.fail("no copy needed")
    )
    assert stage(release) == {"upload": False, "version": VERSION, "files": []}
    assert list(release.output.iterdir()) == []


def test_partial_release_stages_only_the_missing_distribution(release):
    release.remote = published(release, "wheel")
    assert stage(release)["files"] == [SDIST]
    assert [path.name for path in release.output.iterdir()] == [SDIST]


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_differing_published_bytes_refuse_before_any_copy(release, monkeypatch, kind):
    release.remote = published(release, kind)
    release.remote["urls"][0]["digests"]["sha256"] = "f" * 64
    monkeypatch.setattr(
        pypi_assets.shutil, "copyfile", lambda *args: pytest.fail("must not copy")
    )
    with pytest.raises(pypi_assets.PreflightError, match="different bytes"):
        stage(release)
    assert not release.output.exists()


def test_staging_can_be_repeated_without_adding_files(release):
    assert stage(release) == stage(release)
    assert len(list(release.output.iterdir())) == 2


def test_previous_matching_staging_is_removed_once_remote_has_the_files(release):
    stage(release)
    release.remote = published(release, "wheel", "sdist")
    assert not stage(release)["upload"]
    assert list(release.output.iterdir()) == []


def test_matching_previously_staged_published_file_cannot_be_reuploaded(release):
    stage(release)
    release.remote = published(release, "wheel")
    assert stage(release)["files"] == [SDIST]
    assert [path.name for path in release.output.iterdir()] == [SDIST]


@pytest.mark.parametrize(
    "filename,content", [("unrelated.whl", b"stale"), (WHEEL, b"changed")]
)
def test_stale_upload_directory_is_rejected_without_changes(release, filename, content):
    release.output.mkdir()
    stale = release.output / filename
    stale.write_bytes(content)
    with pytest.raises(pypi_assets.PreflightError, match="stale or unverified"):
        stage(release)
    assert stale.read_bytes() == content
    assert len(list(release.output.iterdir())) == 1


@pytest.mark.parametrize("version", ["0.1.0+git.abc1234", "0.1.0rc1", "01.1.0", "1.2"])
def test_only_stable_public_versions_are_accepted(release, version):
    release.record["wheel"]["version"] = version
    save_record(release)
    with pytest.raises(pypi_assets.PreflightError, match="stable X.Y.Z"):
        stage(release)
    assert not release.output.exists()


def test_evidence_requires_both_distribution_records(release):
    del release.record["sdist"]
    save_record(release)
    with pytest.raises(pypi_assets.PreflightError, match="both wheel and sdist"):
        stage(release)


def test_evidence_versions_must_agree(release):
    release.record["sdist"]["version"] = "0.2.0"
    save_record(release)
    with pytest.raises(pypi_assets.PreflightError, match="versions differ"):
        stage(release)


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_missing_distribution_is_rejected(release, kind):
    (release.artifacts / release.record[kind]["name"]).unlink()
    with pytest.raises(pypi_assets.PreflightError, match="missing or symlinked"):
        stage(release)


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_changed_candidate_is_rejected_against_evidence(release, kind):
    (release.artifacts / release.record[kind]["name"]).write_bytes(b"changed")
    with pytest.raises(pypi_assets.PreflightError, match="tested release evidence"):
        stage(release)


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
@pytest.mark.parametrize(
    "field,value", [("name", "another-project"), ("version", "0.2.0")]
)
def test_embedded_distribution_identity_must_match_evidence(
    release, kind, field, value
):
    writer = write_wheel if kind == "wheel" else write_sdist
    path = release.artifacts / release.record[kind]["name"]
    writer(path, **{field: value})
    release.record[kind]["sha256"] = pypi_assets.sha256(path)
    save_record(release)
    with pytest.raises(
        pypi_assets.PreflightError, match="project name|metadata version"
    ):
        stage(release)


@pytest.mark.parametrize(
    "filename", ["another.whl", "trame_vtkjs.zip", "unexpected.exe"]
)
def test_unexpected_artifacts_cannot_enter_upload_directory(release, filename):
    (release.artifacts / filename).write_bytes(b"unexpected")
    with pytest.raises(pypi_assets.PreflightError, match="unexpected release files"):
        stage(release)


def test_evidence_cannot_select_a_path_or_another_archive_extension(release):
    release.record["sdist"]["name"] = "../trame_vtkjs.zip"
    save_record(release)
    with pytest.raises(pypi_assets.PreflightError, match="distribution filename"):
        stage(release)


@pytest.mark.parametrize("remote", [[], {}, {"info": {}}, {"info": {"name": "other"}}])
def test_malformed_or_wrong_project_responses_fail_closed(release, remote):
    release.remote = remote
    with pytest.raises(pypi_assets.PreflightError):
        stage(release)
    assert not release.output.exists()


def test_wrong_published_version_is_rejected(release):
    release.remote = published(release, "wheel")
    release.remote["info"]["version"] = "0.2.0"
    with pytest.raises(pypi_assets.PreflightError, match="unexpected version"):
        stage(release)


def test_unexpected_published_wheel_name_is_rejected(release):
    release.remote = published(release, "wheel")
    release.remote["urls"][0]["filename"] = "trame_vtkjs-0.1.0-py2-none-any.whl"
    with pytest.raises(pypi_assets.PreflightError, match="unexpected or duplicate"):
        stage(release)


def test_duplicate_published_filenames_are_rejected(release):
    release.remote = published(release, "wheel", "wheel")
    with pytest.raises(pypi_assets.PreflightError, match="unexpected or duplicate"):
        stage(release)


@pytest.mark.parametrize("digest", [None, "", "not-a-digest"])
def test_missing_published_digest_is_rejected(release, digest):
    release.remote = published(release, "wheel")
    release.remote["urls"][0]["digests"]["sha256"] = digest
    with pytest.raises(pypi_assets.PreflightError, match="valid SHA256"):
        stage(release)


def test_output_cannot_overlap_release_artifacts(release):
    release.output = release.artifacts
    with pytest.raises(pypi_assets.PreflightError, match="separate"):
        stage(release)


@pytest.mark.parametrize("code", [403, 500])
def test_only_http_404_counts_as_a_missing_release(monkeypatch, code):
    def fail(*args, **kwargs):
        raise HTTPError("https://pypi.org/", code, "failure", {}, None)

    monkeypatch.setattr(pypi_assets, "urlopen", fail)
    with pytest.raises(pypi_assets.PreflightError, match=f"HTTP {code}"):
        pypi_assets.fetch_release(VERSION)


def test_http_404_is_a_missing_release(monkeypatch):
    def absent(request, **kwargs):
        assert request.full_url == f"https://pypi.org/pypi/trame-vtkjs/{VERSION}/json"
        raise HTTPError(request.full_url, 404, "missing", {}, None)

    monkeypatch.setattr(pypi_assets, "urlopen", absent)
    assert pypi_assets.fetch_release(VERSION) is None


def test_network_failure_does_not_count_as_a_missing_release(monkeypatch):
    def fail(*args, **kwargs):
        raise URLError("unavailable")

    monkeypatch.setattr(pypi_assets, "urlopen", fail)
    with pytest.raises(pypi_assets.PreflightError, match="unavailable"):
        pypi_assets.fetch_release(VERSION)


@pytest.mark.parametrize("content", [b"not JSON", b"null", b"[]"])
def test_malformed_pypi_json_fails_closed(monkeypatch, content):
    monkeypatch.setattr(
        pypi_assets, "urlopen", lambda *args, **kwargs: io.BytesIO(content)
    )
    with pytest.raises(pypi_assets.PreflightError, match="lookup failed|malformed"):
        pypi_assets.fetch_release(VERSION)


@pytest.mark.parametrize("already_published", [False, True])
def test_cli_reports_whether_the_publisher_should_upload(
    release, monkeypatch, capsys, already_published
):
    if already_published:
        release.remote = published(release, "wheel", "sdist")
    github_output = release.artifacts.parent / "github-output"
    monkeypatch.setattr(
        pypi_assets.sys,
        "argv",
        [
            "pypi_assets.py",
            "--evidence",
            str(release.evidence),
            "--artifacts",
            str(release.artifacts),
            "--output",
            str(release.output),
            "--github-output",
            str(github_output),
        ],
    )
    pypi_assets.main()
    assert json.loads(capsys.readouterr().out)["upload"] is not already_published
    assert github_output.read_text() == f"upload={str(not already_published).lower()}\n"
