from __future__ import annotations

from trame_vtkjs.widgets.vtkjs_base import VtkJsBaseView


class VtkJsSharedView(VtkJsBaseView):
    _element_name = "vtk-js-shared"
    _ref_prefix = "_vtkjssharedview"


__all__ = ["VtkJsSharedView"]
