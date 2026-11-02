# API and rendering contracts

## Python imports

```python
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
```

The helper modules also expose configuration types and readers.
`streamed_scene_blocks` describes the JSON feature blocks; `view_types` contains
view policy types. Application code should use these supported modules and
widgets rather than importing from the view implementation.

## Views and browser access

`VtkJsLocalView` renders on its own canvas. `VtkJsSharedView` renders in a
host-owned WebGL context; the host controls its canvas, camera, and interaction.
Both accept a Python `vtkRenderWindow`.

The Vue plugin `trame_vtkjs` exports `install`, `VtkJsLocal`, and `VtkJsShared`.
Their element names are `vtk-js-local` and `vtk-js-shared`. Browser hosts resolve
mounted views through `window.trameVtkjs.getView(key)` or `whenView(key)`, and
access the shared matrix helpers through `window.trameVtkjs.glMatrix`.
`trame.modules.vtkjs` exposes module registration and serves the browser runtime
under `__trame_vtkjs`. Scene replication uses protocol v2 with `scene.ops` and
`scene.resync`.

## Publish and recover

Use `view.transaction()` to publish batched VTK mutations and commands together
when the context exits. Use `view.sync()` to flush other pending changes.
Replaced datasets, properties, transforms, and pipeline
connections are tracked automatically. Publication also checks pipeline and
transform MTimes because some VTK operations omit `ModifiedEvent`.

After bypassing VTK modification notifications, call `view.recover()` to scan
MTimes and publish missed changes. Browser resynchronization performs recovery
before returning a snapshot. A serialization failure preserves pending changes
and command order for a later retry.

## Streaming policies

Both views accept these construction options:

| Option | Default | Alternatives |
| --- | --- | --- |
| `tiles3d_texture_policy` | `"auto"` | `"native"`, `"rgba"` |
| `tiles3d_quality_policy` | `"adaptive"` | `"fixed"` |
| `streamed_memory_budget_bytes` | Browser-derived | A page-wide byte allowance |

Automatic texture policy chooses native compression, except for software
renderers and headless browsers, which use RGBA. Views on one page share a memory
allowance and must receive the same value. It covers resident streamed geometry
and textures, not total browser memory or reserved GPU memory. Changing it
requires a page reload.

## External-resource gates

Shared views expose `registerSceneGate(hold)` and `retrySceneGate()`.
`hold(message)` receives an in-order scene message and returns `true` to delay
it, for example until matching video pixels arrive. Held messages keep their
order, while unrelated updates may pass them. Call `retrySceneGate()` when the
resource arrives. A held message applies after three seconds even if its gate
still holds it; request missing resources before that deadline. Snapshots are
never held. Disposing a registration releases its held messages.

## Picking and drag acknowledgement

Gesture `pointer_event` camera matrices and `setRenderedCamera` use column-major
layout in both views. Drag start, move, and end events share an opaque
`gesture_id`. The browser keeps its final preview until the originating view
acknowledges the release after publishing the final scene mutations:

```python
view.send_command("pointer.drag.end", {"gesture_id": event["gesture_id"]})
```

Send this command even for unchanged, cancelled, or rejected drops, using
`finally` when a handler can exit early. Do not retain it. Async handlers must
await scene mutations before acknowledging. The ordered acknowledgement makes
the server position authoritative.

For points that move between render buckets, use the same nonempty
`preview_group` in `make_pickable` for every bucket in a layer. IDs must be unique
within the group, using one coordinate system and preview mode. Give independent
layers distinct groups. Previews follow `(preview_group, point_id)` across
buckets; duplicate IDs or removed targets stop them safely. Points keep
independent pending previews, and a regrab transfers its point to the new gesture.

## Point mapper limits

For direct `vtkPointGaussianMapper` scenes, explicitly call
`mapper.SetScaleFactor(0)` to select simple points. Nonzero scale factors,
anisotropy, Gaussian arrays/functions, rotations, and custom splat shaders raise
translation errors. `Emissive` and `BoundScale` are not forwarded in this mode.

Point size comes from the actor property. The direct-cloud presentation block
uses vtk.js `pointSizeScale` for CSS pixels without changing `scaleFactor`.
Streamed scenes construct their mappers in the browser and control the resident
draw prefix there.
