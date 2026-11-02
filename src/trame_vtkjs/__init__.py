from __future__ import annotations

from typing import TYPE_CHECKING, Union

from trame_client.utils.version import get_version

from trame_vtkjs.view_types import Tiles3DQualityPolicy, Tiles3DTexturePolicy

if TYPE_CHECKING:
    from trame_vtkjs.streamed_scene import (
        PointCloudSource,
        StreamedSceneActor,
        Tiles3DSource,
    )

__version__: str = get_version("trame-vtkjs")

__all__ = [
    "PointCloudSource",
    "StreamedSceneActor",
    "Tiles3DSource",
    "Tiles3DQualityPolicy",
    "Tiles3DTexturePolicy",
    "__version__",
]


def __getattr__(
    name: str,
) -> type[Union[PointCloudSource, StreamedSceneActor, Tiles3DSource]]:
    # Resolved lazily so trame_vtkjs.store and trame_vtkjs.wire import
    # without VTK or a built web bundle.
    if name in {"PointCloudSource", "StreamedSceneActor", "Tiles3DSource"}:
        from trame_vtkjs import streamed_scene

        public_type: type[Union[PointCloudSource, StreamedSceneActor, Tiles3DSource]]
        public_type = getattr(streamed_scene, name)
        return public_type
    raise AttributeError(name)
