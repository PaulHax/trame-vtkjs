import json
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile


def test_offline_tiles3d_runtime_is_staged_and_selected_for_wheel(tmp_path):
    root = Path(__file__).resolve().parents[1]
    serve = root / "src" / "trame_vtkjs" / "module" / "serve"
    required = {
        "js/trame_vtkjs.umd.js",
        "js/tiles3dDecodeWorker.classic.js",
        "wasm/tiles3d/draco_wasm_wrapper.js",
        "wasm/tiles3d/draco_decoder.wasm",
        "wasm/tiles3d/basis_encoder.js",
        "wasm/tiles3d/basis_encoder.wasm",
    }
    assert all((serve / relative).is_file() for relative in required)
    runtime_exports = {
        "js/tiles3dDecodeWorker.classic.js": "tiled-vtkjs/tiles3d/decode-worker",
        "wasm/tiles3d/draco_wasm_wrapper.js": "tiled-vtkjs/tiles3d/codecs/draco_wasm_wrapper.js",
        "wasm/tiles3d/draco_decoder.wasm": "tiled-vtkjs/tiles3d/codecs/draco_decoder.wasm",
        "wasm/tiles3d/basis_encoder.js": "tiled-vtkjs/tiles3d/codecs/basis_encoder.js",
        "wasm/tiles3d/basis_encoder.wasm": "tiled-vtkjs/tiles3d/codecs/basis_encoder.wasm",
    }
    resolution = subprocess.run(
        [
            "node",
            "--eval",
            "const exports = JSON.parse(process.argv[1]); "
            "console.log(JSON.stringify(Object.fromEntries("
            "Object.entries(exports).map(([name, specifier]) => "
            "[name, require.resolve(specifier)]))));",
            json.dumps(runtime_exports),
        ],
        cwd=root / "vue-components",
        check=True,
        capture_output=True,
        text=True,
    )
    for relative, source in json.loads(resolution.stdout).items():
        assert (serve / relative).read_bytes() == Path(source).read_bytes()

    # Anything else a checkout holds under serve/wasm/ must stay out.
    stray = serve / "wasm" / "stale-runtime"
    stray.mkdir(exist_ok=True)
    (stray / "unpackaged.bin").write_bytes(b"unpackaged runtime")
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(tmp_path),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        shutil.rmtree(stray)
    wheel = next(tmp_path.glob("*.whl"))
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())
        for relative in required:
            assert (
                archive.read("trame_vtkjs/module/serve/" + relative)
                == (serve / relative).read_bytes()
            )
    prefix = "trame_vtkjs/module/serve/"
    assert {prefix + relative for relative in required} <= names
    assert {name for name in names if name.startswith(prefix + "wasm/")} == {
        prefix + relative for relative in required if relative.startswith("wasm/")
    }
