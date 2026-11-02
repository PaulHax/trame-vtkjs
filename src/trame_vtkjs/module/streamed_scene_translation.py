"""Actor-specific translation for the synthetic streamed scene anchor."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from vtkmodules.vtkRenderingCore import vtkActor

from trame_vtkjs.module.feature_blocks import get_block
from trame_vtkjs.module.vtkjs_translator import actor_user_matrix_property
from trame_vtkjs.streamed_scene import STREAMED_SCENE_BLOCK, STREAMED_SCENE_TYPE

if TYPE_CHECKING:
    from trame_vtkjs.module.state_cache import SceneReader, VtkState
    from trame_vtkjs.store import RefSlot


def translate_actor(
    reader: SceneReader,
    state: VtkState,
    props: dict[str, object],
    refs: dict[str, RefSlot],
) -> tuple[str, dict[str, object], dict[str, RefSlot], dict[str, Mapping[str, object]]]:
    """Preserve actor props while replacing drawable refs for streaming."""
    actor = reader.vtk_object(state["Id"])
    if not isinstance(actor, vtkActor):
        raise RuntimeError(f"vtkActor state {state['Id']} has no live vtkActor")
    user_matrix = actor_user_matrix_property(actor)
    if user_matrix is not None:
        props["userMatrix"] = user_matrix

    block = get_block(actor, STREAMED_SCENE_BLOCK)
    if block is None:
        return "vtkActor", props, refs, {}
    return STREAMED_SCENE_TYPE, props, {}, {STREAMED_SCENE_BLOCK: block}
