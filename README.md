# trame-vtkjs

Render Python VTK scenes in the browser with vtk.js. The Python server and
browser client ship together in one wheel, with scene updates, picking,
streaming, and recovery across connected clients.

| View | Rendering context |
| --- | --- |
| `VtkJsLocalView` | Own canvas and camera controls |
| `VtkJsSharedView` | Host-owned WebGL context, including MapLibre |

## Install and try it

Install a wheel built from this repository or downloaded from its releases:

```sh
python -m pip install "./dist/trame_vtkjs-<version>-py3-none-any.whl[vtk]"
```

The `vtk` extra installs the supported VTK 9.6 series. The Python namespace is
`trame_vtkjs`; application widgets are available through trame:

```python
from trame.widgets.vtkjs import VtkJsLocalView, VtkJsSharedView
```

From the checkout, run the interactive cone example:

```sh
python examples/vtk/vtkjs_cone.py
```

The [MapLibre example](examples/vtk/maplibre_demo/README.md) combines shared
rendering, textures, editable landmarks, and streamed geometry.

## Documentation

- [API and rendering contracts](docs/api.md)
- [Build and test](docs/development.md)
- [Releases and publisher setup](docs/releases.md)
- [Contributing](CONTRIBUTING.md)

Licensed under [Apache 2.0](LICENSE), retaining Kitware's copyright and
attribution. Maintained by Paul Elliott.
