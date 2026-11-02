"""Exercise the wheel's registered browser assets and offline codec runtimes."""

import hashlib
from pathlib import Path

import pytest
from playwright.sync_api import expect

from trame_vtkjs import module

pytestmark = pytest.mark.js_oracle


@pytest.fixture
def server_path():
    return "examples/tests/rendering/shared_gl.py"


def test_registered_assets_and_offline_workers(server, page):
    root = Path(module.serve_path)
    base_url = f"http://127.0.0.1:{server.port}"
    with page.expect_response(lambda r: "trame_vtkjs.umd.js" in r.url) as response:
        page.goto(f"{base_url}/")
    expect(page.locator(".readyCount")).not_to_have_text("0")
    assert hashlib.sha256(response.value.body()).digest() == hashlib.sha256(
        (root / "js/trame_vtkjs.umd.js").read_bytes()
    ).digest()
    assert page.evaluate(
        """() => ['install', 'VtkJsLocal', 'VtkJsShared'].every(
          key => Boolean(window.trame_vtkjs[key])) &&
          Boolean(window.trameVtkjs.glMatrix)"""
    )

    assets = [
        "js/tiles3dDecodeWorker.classic.js",
        "wasm/tiles3d/draco_wasm_wrapper.js",
        "wasm/tiles3d/draco_decoder.wasm",
        "wasm/tiles3d/basis_encoder.js",
        "wasm/tiles3d/basis_encoder.wasm",
    ]
    for asset in assets:
        served = page.request.get(f"{base_url}/__trame_vtkjs/{asset}")
        assert served.ok, asset
        assert hashlib.sha256(served.body()).digest() == hashlib.sha256(
            (root / asset).read_bytes()
        ).digest(), asset

    result = page.evaluate(
        """async () => {
          const worker = new Worker('/__trame_vtkjs/js/tiles3dDecodeWorker.classic.js');
          try {
            return await new Promise((resolve, reject) => {
              worker.onerror = event => reject(new Error(event.message));
              worker.onmessage = event => resolve(event.data);
              worker.postMessage({kind: 'decode', jobId: 1, request: {
                content: new ArrayBuffer(0),
                contentUrl: `${location.origin}/empty.glb`, revision: 'assets',
                accumulatedTransform: [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],
                tilesetToScene: [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],
                textureCapabilities: {capabilityKey: 'assets', compressedFormats: []}
              }});
            });
          } finally { worker.terminate(); }
        }"""
    )
    assert result["jobId"] == 1
    assert result["kind"] == "error"
    assert result["error"]["name"] == "TileDecodeError"

    codecs = page.evaluate(
        """async () => {
          const source = `onmessage = async ({data: base}) => {
            try {
              importScripts(base + '/draco_wasm_wrapper.js', base + '/basis_encoder.js');
              const binary = async name => {
                const response = await fetch(base + '/' + name);
                if (!response.ok) throw new Error(name + ': ' + response.status);
                return response.arrayBuffer();
              };
              const draco = await DracoDecoderModule({wasmBinary: await binary('draco_decoder.wasm')});
              const basis = await BASIS({wasmBinary: await binary('basis_encoder.wasm')});
              basis.initializeBasis();
              postMessage({draco: typeof draco.Decoder === 'function',
                basis: typeof basis.KTX2File === 'function'});
            } catch (error) { postMessage({error: String(error)}); }
          };`;
          const url = URL.createObjectURL(new Blob([source], {type: 'text/javascript'}));
          const worker = new Worker(url);
          try {
            return await new Promise((resolve, reject) => {
              worker.onerror = event => reject(new Error(event.message));
              worker.onmessage = event => resolve(event.data);
              worker.postMessage(`${location.origin}/__trame_vtkjs/wasm/tiles3d`);
            });
          } finally { worker.terminate(); URL.revokeObjectURL(url); }
        }"""
    )
    assert codecs == {"draco": True, "basis": True}
