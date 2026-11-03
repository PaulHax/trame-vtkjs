# Build and test

Use Python 3.10 and Node.js 24 for development, matching CI. Work from the
repository root with npm available. The browser
bundle needs the exact vtk.js commit in [`vtkjs-fork.env`](../vtkjs-fork.env).

## Build the renderer and browser client

```sh
bridge_root="$PWD"
source ./vtkjs-fork.env
vtkjs_build="$(dirname "$bridge_root")/vtk-js-build"
git clone "$VTKJS_FORK_REPO" "$vtkjs_build"
git -C "$vtkjs_build" checkout --detach "$VTKJS_FORK_COMMIT"
(
  cd "$vtkjs_build"
  npm ci
  npm run build:esm
  cd dist/esm
  npm link
)
(
  cd "$bridge_root/vue-components"
  npm ci
  npm link @kitware/vtk.js
  npm run build
)
```

Use an existing clean renderer checkout at the pinned commit if one is available.
The `tiled-vtkjs` dependency must come from its integrity-checked lockfile,
not a linked development tree. Rebuild the browser client after changing its
source; Python serves the built files.

## Install development dependencies

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[vtk,dev]" -r tests/requirements.txt
```

## Run checks

```sh
(cd vue-components && npm test)
python -m pytest -m "not js_oracle" \
  --ignore=tests/push_oracle_e2e --ignore=tests/test_shared_gl_context.py
python -m playwright install chromium
python -m pytest tests/test_shared_gl_context.py tests/push_oracle_e2e \
  tests/test_module_assets_e2e.py --browser chromium
```

Browser checks run headless by default. MapLibre checks additionally need local
vendor files; see the [example guide](../examples/vtk/maplibre_demo/README.md).
Headless runs establish correctness, not hardware performance.

## Build distributable artifacts

From committed source, with the renderer link available:

```sh
./release.sh build
./release.sh verify
```

The script installs the locked browser dependencies, rebuilds the served client
and streaming codecs, and verifies wheel/sdist contents and dependency revisions.
Artifacts and evidence go in `dist/`. These commands publish nothing. See
[releases](releases.md) for public versions and publisher setup.
