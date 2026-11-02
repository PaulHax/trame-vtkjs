trame-vtkjs
===========

Local rendering for trame: a server-side ``vtkRenderWindow`` is published as a
flat scene and drawn in the browser with vtk.js, either on the view's own canvas
(``VtkJsLocalView``) or inside a host's WebGL context (``VtkJsSharedView``).
Shared views can render inside MapLibre while the map owns the canvas, camera
and interaction.

License
----------------------------------------

This project is licensed under Apache 2.0. It preserves the Kitware copyright
and attribution in ``LICENSE`` and the useful development history of the
vtk.js bridge. It is maintained independently from Kitware's trame-vtklocal,
which is a different product built around VTK WASM.

Installation
----------------------------------------

Install a wheel built from this repository, either from its GitHub releases or
from ``dist/`` after a local build. The distribution is ``trame-vtkjs`` and the
Python import namespace is ``trame_vtkjs``. The browser client is packaged in
the same wheel; there is no separate npm release to install.

.. code-block:: console

    python -m pip install "dist/trame_vtkjs-<version>-py3-none-any.whl[vtk]"

The ``vtk`` extra selects the supported VTK 9.6 series. VTK 9.7 needs separate
scene reconciliation qualification. The release workflow publishes ``trame-vtkjs`` to PyPI after release-causing
commits reach ``main`` and the trusted publisher is configured. See
``RELEASING.md`` for the initial repository and publisher setup.

Public Python API
----------------------------------------

.. code-block:: python

    from trame.widgets.vtkjs import VtkJsLocalView, VtkJsSharedView
    from trame_vtkjs import (
        PointCloudSource, StreamedSceneActor, Tiles3DSource,
        Tiles3DQualityPolicy, Tiles3DTexturePolicy,
    )
    from trame_vtkjs.interaction import make_pickable, clear_pickable, PickPreview
    from trame_vtkjs.projected_texture import (
        MODE_HOMOGRAPHY, MODE_WORLD_TO_CLIP,
        mark_projected_texture, set_projected_texture_matrix,
    )
    from trame_vtkjs.screen_size_glyphs import mark_screen_size_glyphs
    from trame_vtkjs.streamed_scene import DEFAULT_ADAPTIVE_MIN_BUDGET, source_block
    from trame_vtkjs.streamed_scene_blocks import AdaptiveOptions, Presentation

The interaction, projected texture and screen size glyph modules also expose
their configuration types and readers. ``streamed_scene_blocks`` describes the
JSON feature blocks. These modules and ``view_types`` are supported application
imports. ``module`` and the view implementation modules are internal.

``trame.widgets.vtkjs`` exports both views and initializes the trame module;
``trame.modules.vtkjs`` exposes its registration. The Vue plugin is
``trame_vtkjs`` and exports ``install``, ``VtkJsLocal`` and ``VtkJsShared``. The
``VtkJsLocalView`` and ``VtkJsSharedView`` classes retain their
``vtk-js-local`` and ``vtk-js-shared`` elements. Browser hosts use
``window.trameVtkjs.getView(key)``, ``whenView(key)`` and ``glMatrix``.

The module serves ``__trame_vtkjs/js/trame_vtkjs.umd.js`` and the offline
worker/codecs under ``__trame_vtkjs``. Worker filenames and the 3D Tiles codec
layout belong to pointcloud-lod 0.12.6. Scene replication remains protocol v2
with ``scene.ops`` and ``scene.resync``.


Development
----------------------------------------

Build and install the Vue components. The bundle needs the vtk-js fork built at
the exact commit recorded in ``vtkjs-fork.env`` (``VTKJS_FORK_COMMIT``), the
only place that sha is written, so this README, ``release.sh`` and CI cannot
disagree about which vtk.js the bundle carries.

.. code-block:: console

    source ./vtkjs-fork.env
    git clone "$VTKJS_FORK_REPO" ../vtk-js-stuff/external-context-integration
    cd ../vtk-js-stuff/external-context-integration
    git checkout "$VTKJS_FORK_COMMIT"
    npm ci
    npm run build:esm
    cd dist/esm
    npm link
    cd ../../../trame-vtkjs/vue-components
    npm ci
    npm link @kitware/vtk.js
    npm run build
    cd -

``npm ci`` (not ``npm i``) is what installs the locked, integrity-checked
``pointcloud-lod`` release; ``release.sh`` refuses to build a wheel against a
``npm link``-ed working copy of it.

Install the library

.. code-block:: console

    pip install -e .

Release flow
----------------------------------------

Pull requests validate Conventional Commit messages, build the locked browser
runtime, and test the installed wheel. On ``main``, Python Semantic Release's
conventional parser and version calculation select a public ``X.Y.Z`` version
before the distributions are built. The first product release is ``0.1.0``;
``feat`` selects a minor release, ``fix`` and ``perf`` select a patch release,
and ordinary documentation/maintenance commits do not publish. Breaking changes
select a minor release before 1.0 and a major release thereafter.

Product tags use ``trame-vtkjs-vX.Y.Z``, excluding inherited releases for other
product identities. No version or changelog commit changes the source revision
between testing and publication. ``build-info.json`` records the exact source
commit, tree, dependency pins and browser bundle hash inside every wheel.

``.github/workflows/release.yml`` builds the wheel and source distribution once,
checks that they contain the same runtime assets, installs and tests the wheel,
and transfers those artifacts to separate GitHub and PyPI publication jobs.
The PyPI job uses OIDC trusted publishing through the ``pypi`` environment.
It does not check out or rebuild the source. Existing GitHub/PyPI files must
match the tested bytes; conflicting files stop the release.

Local development builds retain ``0.1.0+git.<sha>`` versions and publish nothing:

.. code-block:: console

    ./release.sh build
    ./release.sh verify

A public build supplies ``TRAME_VTKJS_RELEASE_VERSION`` from the release plan.
Its source distribution preserves that version and the built browser assets,
so consumers can build a wheel without Git, npm or a release environment.

The build requires the pinned vtk-js fork linked into ``vue-components``.
``release.sh`` installs the integrity-checked pointcloud-lod lock, rebuilds the
actual served UMD/worker/codecs, verifies the complete dependency chain and
writes ``dist/release-evidence.json``. Neither ``build`` nor ``verify`` uploads
anything. ``publish`` uploads only those verified artifacts to GitHub; PyPI
publication belongs to the workflow's isolated trusted-publisher job.

See ``RELEASING.md`` for commit rules, first-release setup, registry recovery,
workflow permissions and the exact trusted-publisher fields.


Running examples
----------------------------------------

.. code-block:: console

    pip install trame trame-vuetify
    # Install the built trame-vtkjs wheel with its vtk extra as above.

    # a cone rendered with vtk.js on the view's own canvas
    python ./examples/vtk/vtkjs_cone.py

    # vtk.js layered renderers: preserve color while resetting overlay depth
    python ./examples/vtk/vtkjs_layered_renderers.py

3D Tiles host policies
----------------------------------------

``VtkJsLocalView`` and ``VtkJsSharedView`` accept declarative policy options
from Python. Texture policy defaults to ``"auto"``, which selects native GPU
compression except when a software renderer or headless browser requires RGBA.
Set it to ``"native"`` or ``"rgba"`` to override that detection. Quality
policy defaults to ``"adaptive"`` and may be set to ``"fixed"`` for controlled
comparisons.

.. code-block:: python

    view = VtkJsSharedView(
        render_window,
        tiles3d_texture_policy="rgba",
        tiles3d_quality_policy="fixed",
    )


Scene gate for external resources
---------------------------------

``VtkJsSharedView`` exposes ``registerSceneGate(hold)`` and
``retrySceneGate()``. ``hold(message)`` receives each in-order scene ops
message before it applies and returns ``true`` to hold it, for example while
the video frame a retained ``video.frame.<key>`` command names has not
arrived. Held messages keep their order: a later message the gate also holds
queues behind them, while one it would not hold applies them first, so an
unrelated update never waits on the resource. Call ``retrySceneGate()`` when
the awaited resource lands; a held message also applies at its deadline (3 s)
whatever the gate says, so a resource that never arrives cannot stall the
view. Ask for the resource again well before that deadline rather than
relying on it. Snapshots are never held.
The registration disposer releases anything the gate held.

PointGaussianMapper support
---------------------------

The vtk.js backend implements only simple points. Python callers must explicitly
call ``mapper.SetScaleFactor(0)``. Nonzero scale factors, anisotropy, Gaussian
scale/opacity arrays or functions, rotation arrays, and custom splat shaders
raise an error during scene translation. Gaussian-only defaults such as
``Emissive`` and ``BoundScale`` are not forwarded and have no effect in this mode.

Point size comes from the actor property. The direct-cloud presentation block
converts CSS pixels with the vtk.js ``pointSizeScale`` extension; it does not
change ``scaleFactor``. Streamed scenes create their simple-point mappers in the
browser, where the renderer also controls the resident-buffer draw prefix.

Scene publication and recovery
------------------------------

For vtk.js views, ``view.transaction()`` batches ordinary VTK mutations and
commands into one publication; ``view.sync()`` flushes pending changes. Replaced
dependencies are tracked automatically, including shared datasets, properties,
and pipeline connections. Pipeline and transform aggregate MTimes are checked
at publication because some VTK operations do not emit ``ModifiedEvent``.

After deliberately bypassing VTK modification notifications, call
``view.recover()`` to scan observed MTimes and publish missed changes. Browser
resynchronization performs this recovery before returning its snapshot.
A failed pre-commit serialization preserves pending changes and command order
for a later retry.


MapLibre shared-context example
-------------------------------

``examples/vtk/maplibre_vtkjs.py`` exercises shared MapLibre rendering,
three renderer layers, delayed projected textures, screen-sized pickable
glyphs, direct and streamed clouds, a textured 3D Tiles mesh, and dependency
replacement across two views. See ``examples/vtk/maplibre_demo/README.md`` for
controls and reproducible headless checks.

Gesture ``pointer_event`` camera matrices use column-major layout for both
local and shared views, matching ``setRenderedCamera``.

Drag release acknowledgement
----------------------------

Drag events carry an opaque ``gesture_id`` shared by their start, moves and
end. The browser holds the final preview position after release so delayed
scene updates cannot replay earlier pointer positions. After processing a
``target.drag.end`` event, the application must enqueue an acknowledgement on
the originating view, after publishing any final scene mutations::

    view.send_command("pointer.drag.end", {"gesture_id": event["gesture_id"]})

Send the acknowledgement even when the drop is unchanged, cancelled or
rejected. Use ``finally`` if the handler may return early. Do not retain the
command. The acknowledgement shares the ordered scene stream with the final
position; once applied, the server position becomes authoritative. Async
handlers must await their scene mutations before acknowledging the release.

For points that move between render buckets, pass the same nonempty
``preview_group`` to ``make_pickable`` for every bucket in one layer. Provide
stable ``ids`` that are unique within that group and use one coordinate system
and preview mode throughout it. Use a distinct group for every independent
layer or dataset. The preview follows ``(preview_group, point_id)`` across
buckets; duplicate identities or a removed target stop that preview safely.
Different points retain independent pending previews, and a regrab transfers
that point's preview to the new gesture.

Streamed memory allowance
-------------------------

``VtkJsLocalView`` and ``VtkJsSharedView`` accept
``streamed_memory_budget_bytes`` at construction. All views on a page share
one allowance; pass the same value to each view. Omit it to use the
browser-derived default. This controls resident streamed geometry and textures,
not total browser memory, and does not detect or reserve GPU memory. Changing
the allowance requires a page reload.
