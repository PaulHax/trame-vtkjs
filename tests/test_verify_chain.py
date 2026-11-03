import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "verify_chain", Path(__file__).resolve().parents[1] / "verify_chain.py"
)
verify_chain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_chain)

RELEASE = {
    "version": "0.13.0",
    "resolved": "https://registry.npmjs.org/tiled-vtkjs/-/tiled-vtkjs-0.13.0.tgz",
    "integrity": (
        "sha512-e8T8hIXiwTfCfYkXV/U/o/mb3jy2tpAexGJEK1VLYMGhvn2PLXIyxyFHrDamKmKl"
        "KNY9Fa9rOS4HFntQ1sXQIg=="
    ),
    "sourceRevision": "83889b7b96457f1e32871164d6524ddba47607f7",
}


def write_json(path, value):
    path.write_text(json.dumps(value))


@pytest.fixture
def install(tmp_path, monkeypatch):
    monkeypatch.setattr(verify_chain, "VUE", tmp_path)
    package = tmp_path / "node_modules" / "tiled-vtkjs"
    package.mkdir(parents=True)
    # Only the neutral core subpath is available to Node in this host fixture.
    write_json(
        package / "package.json",
        {
            "name": "tiled-vtkjs",
            "version": "0.13.0",
            "type": "module",
            "exports": {"./core": "./core.js"},
        },
    )
    (package / "core.js").write_text(
        "export const ADAPTIVE_QUALITY_DEFAULTS = { minBudget: 200000 };\n"
    )
    write_json(tmp_path / "package.json", {"dependencies": {"tiled-vtkjs": "0.13.0"}})
    entry = {key: value for key, value in RELEASE.items() if key != "sourceRevision"}

    def lock(**overrides):
        write_json(
            tmp_path / "package-lock.json",
            {"packages": {"node_modules/tiled-vtkjs": {**entry, **overrides}}},
        )

    lock()
    source = tmp_path / "streamed_scene.py"
    source.write_text("DEFAULT_ADAPTIVE_MIN_BUDGET = 200_000\n")
    monkeypatch.setattr(verify_chain, "STREAMED_SCENE_PY", source)
    return SimpleNamespace(root=tmp_path, package=package, lock=lock, source=source)


def test_verified_registry_release_records_its_source_revision(install):
    assert verify_chain.check_tiled_vtkjs() == RELEASE


@pytest.mark.parametrize(
    "url",
    [
        "https://registry.npmjs.org/tiled-vtkjs/-/tiled-vtkjs-0.13.1.tgz",
        "https://registry.npmjs.org/another-package/-/another-package-0.13.0.tgz",
        "https://github.com/PaulHax/tiled-vtkjs/releases/download/v0.13.0/tiled-vtkjs-0.13.0.tgz",
        "file:vendor/tiled-vtkjs-83889b7b96457f1e32871164d6524ddba47607f7.tgz",
    ],
)
def test_rejects_other_registry_bytes_and_hand_packed_archives(install, url):
    install.lock(resolved=url)
    with pytest.raises(SystemExit, match="lock resolved"):
        verify_chain.check_tiled_vtkjs()


@pytest.mark.parametrize("integrity", ["", "sha512-different-bytes"])
def test_registry_release_requires_its_verified_integrity(install, integrity):
    install.lock(integrity=integrity)
    with pytest.raises(SystemExit, match="lock integrity"):
        verify_chain.check_tiled_vtkjs()


def test_same_release_url_cannot_claim_another_version(install):
    install.lock(version="0.13.1")
    with pytest.raises(SystemExit, match="lock version"):
        verify_chain.check_tiled_vtkjs()


@pytest.mark.parametrize("specification", ["^0.13.0", "latest"])
def test_manifest_must_pin_the_verified_release(install, specification):
    write_json(
        install.root / "package.json", {"dependencies": {"tiled-vtkjs": specification}}
    )
    with pytest.raises(
        SystemExit, match="pin the verified tiled-vtkjs release exactly"
    ):
        verify_chain.check_tiled_vtkjs()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", "another-package", "identify"),
        ("version", "0.13.1", "installed tiled-vtkjs"),
    ],
)
def test_installed_package_must_match_the_verified_release(
    install, field, value, message
):
    path = install.package / "package.json"
    write_json(path, {**json.loads(path.read_text()), field: value})
    with pytest.raises(SystemExit, match=message):
        verify_chain.check_tiled_vtkjs()


def test_working_copy_symlink_cannot_supply_release_bytes(install):
    target = install.root / "working-copy"
    install.package.rename(target)
    install.package.symlink_to(target, target_is_directory=True)
    with pytest.raises(SystemExit, match="symlink"):
        verify_chain.check_tiled_vtkjs()


def test_adaptive_floor_is_read_from_neutral_core_export(install):
    assert verify_chain.check_adaptive_floor() == {"minBudget": 200_000}


def test_adaptive_floor_disagreement_refuses_the_release(install):
    install.source.write_text("DEFAULT_ADAPTIVE_MIN_BUDGET = 100_000\n")
    with pytest.raises(SystemExit, match="accept different max_budget"):
        verify_chain.check_adaptive_floor()


def test_missing_adaptive_floor_export_refuses_the_release(install):
    (install.package / "core.js").write_text("export const unrelated = 1;\n")
    with pytest.raises(SystemExit, match="no longer exports"):
        verify_chain.check_adaptive_floor()


def test_renderer_cannot_declare_a_registry_vtkjs_range(install):
    path = install.package / "package.json"
    write_json(
        path,
        {
            **json.loads(path.read_text()),
            "peerDependencies": {"@kitware/vtk.js": "^38.0.4"},
        },
    )
    with pytest.raises(SystemExit, match="renderer adapter cannot use"):
        verify_chain.check_no_vtkjs_range()


def test_build_metadata_uses_the_new_dependency_identity(install, monkeypatch):
    umd = install.root / "bundle.js"
    umd.write_text(
        "\n".join(
            f'classHierarchy.push("{name}");'
            for name in (
                "vtkPointGaussianMapper",
                "vtkOpenGLPointGaussianMapper",
                "vtkOpenGLPolyDataMapper",
                "vtkOpenGLActor",
            )
        )
        + '\n["pointSizeScale", "circle", "worldSize"];\n'
    )
    build_info = install.root / "build-info.json"
    monkeypatch.setattr(verify_chain, "read_pin", lambda: {})
    monkeypatch.setattr(
        verify_chain,
        "check_vtkjs",
        lambda pin: {"commit": "a" * 40, "branch": "pinned-fork"},
    )
    monkeypatch.setattr(
        verify_chain.sys,
        "argv",
        ["verify_chain.py", "--umd", str(umd), "--build-info", str(build_info)],
    )
    verify_chain.main()
    info = json.loads(build_info.read_text())
    assert info["tiledVtkjs"] == {**RELEASE, "minBudget": 200_000}
    assert "pointcloudLod" not in info
