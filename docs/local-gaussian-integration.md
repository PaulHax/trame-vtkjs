# Local Gaussian integration

This branch integrates tiled-vtkjs's memory-first Gaussian stack for the
TeleSculptor Web city preview. It is a local integration, not a public release.

Exact sources:

- tiled-vtkjs: `87a36fd48ea775ae880516256a7f332b7ec50a74`
- vtk.js: `147c0e8c2635559512fa277db81590706b239159`

`local-dependencies/tiled-vtkjs-source.json` binds the source revision to the
archived package bytes. `vue-components/package-lock.json` records the same
archive and integrity. The package is installed as real files, not a mutable
development link. Keep the existing renderer link intact during local work;
use `npm install --package-lock-only` when updating the lockfile.

After building `vue-components`, verify the installed archive and renderer:

```sh
.venv/bin/python verify_local_chain.py --tiled-source /path/to/clean/tiled-vtkjs
```

The verifier writes `src/trame_vtkjs/module/serve/js/build-info.json` with the
source commits, archive integrity, and bundle checksum. Commit bridge source
before generating final evidence and building its local wheel with `uv build
--wheel`. The app pins that exact wheel and its checksum through `uv.lock`.
The existing `verify_chain.py` remains the production release verifier and
continues to require a published registry release; no publication requirement
has been bypassed for production.

Each view injects the Gaussian content adapter factory. Mesh appearance
wrappers forward a physical `realizationRenderer`, so layers share one sort
manager while retaining their mesh controls. The worker is created on first
sort and terminated with its manager. The build bundles the exported worker
and its shared import graph into a standalone served module.

While splats are displayed, the view installs the Gaussian alpha pass. Hiding
or removing the last displayed splats restores the original render passes;
teardown restores those passes and disposes the custom pass and manager.
Native VTK point mappers, whose server contract allows only simple points,
realize with PointSpriteMapper to retain CSS sizing. Gaussian tile content
constructs the anisotropic Gaussian mapper independently.

The local app preview has its own attribution and documented detail/placement
limits. Headless browser checks establish correctness, not hardware throughput.
