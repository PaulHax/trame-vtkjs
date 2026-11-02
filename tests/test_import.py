from importlib.metadata import distribution, version
from pathlib import Path


def test_public_views_and_module_registration():
    from trame.modules import vtkjs as vtkjs_module
    from trame.widgets import vtkjs
    from trame_vtkjs import module
    from trame_vtkjs.widgets import VtkJsLocalView, VtkJsSharedView

    assert vtkjs.VtkJsLocalView is VtkJsLocalView
    assert vtkjs.VtkJsSharedView is VtkJsSharedView
    assert VtkJsLocalView._element_name == "vtk-js-local"
    assert VtkJsSharedView._element_name == "vtk-js-shared"
    assert vtkjs_module.serve == module.serve
    assert module.vue_use == ["trame_vtkjs"]
    assert list(module.serve) == ["__trame_vtkjs"]
    assert module.scripts[0].startswith("__trame_vtkjs/js/trame_vtkjs.umd.js?v=")
    assert (Path(module.serve["__trame_vtkjs"]) / "js/trame_vtkjs.umd.js").is_file()


def test_distribution_and_supported_application_imports():
    import trame_vtkjs
    from trame_vtkjs import (
        PointCloudSource,
        StreamedSceneActor,
        Tiles3DSource,
        Tiles3DQualityPolicy,
        Tiles3DTexturePolicy,
    )
    from trame_vtkjs.interaction import (
        PickPreview,
        clear_pickable,
        make_pickable,
        pickable_config,
    )
    from trame_vtkjs.projected_texture import (
        MODE_HOMOGRAPHY,
        MODE_WORLD_TO_CLIP,
        mark_projected_texture,
        projected_texture_config,
        set_projected_texture_matrix,
    )
    from trame_vtkjs.screen_size_glyphs import (
        mark_screen_size_glyphs,
        screen_size_glyphs_config,
    )
    from trame_vtkjs.streamed_scene import DEFAULT_ADAPTIVE_MIN_BUDGET, source_block
    from trame_vtkjs.streamed_scene_blocks import (
        AdaptiveOptions,
        AutoPresentation,
        FixedPresentation,
        Presentation,
    )

    assert trame_vtkjs.__version__ == version("trame-vtkjs")
    installed = distribution("trame-vtkjs")
    assert installed.metadata["Name"] == "trame-vtkjs"
    assert not any(
        str(path).startswith("trame_vtklocal/")
        or str(path) in {"trame/widgets/vtklocal.py", "trame/modules/vtklocal.py"}
        for path in installed.files or ()
    )
    assert PointCloudSource and StreamedSceneActor and Tiles3DSource
    assert Tiles3DQualityPolicy and Tiles3DTexturePolicy and PickPreview
    assert AdaptiveOptions and AutoPresentation and FixedPresentation and Presentation
    assert MODE_HOMOGRAPHY == "homography"
    assert MODE_WORLD_TO_CLIP == "worldToClip"
    assert DEFAULT_ADAPTIVE_MIN_BUDGET == 200_000
    assert all(
        callable(function)
        for function in (
            clear_pickable,
            make_pickable,
            pickable_config,
            mark_projected_texture,
            projected_texture_config,
            set_projected_texture_matrix,
            mark_screen_size_glyphs,
            screen_size_glyphs_config,
            source_block,
        )
    )
