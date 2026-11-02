from trame_vtkjs.widgets.vtkjs_view import *  # noqa F403
from trame_vtkjs.widgets.vtkjs_shared_view import *  # noqa F403
from trame_vtkjs import host_types as _host_types


def initialize(server: "_host_types.ModuleHostServer") -> None:
    from trame_vtkjs import module

    server.enable_module(module)
