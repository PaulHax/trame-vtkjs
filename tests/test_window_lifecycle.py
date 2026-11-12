"""Closing a view retires its data while other views keep publishing."""

import gc

import numpy as np
from trame.app import get_server
from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
from vtkmodules.vtkRenderingCore import vtkRenderer, vtkRenderWindow

from push_oracle.scenes import add_actor, populate_quad
from trame_vtkjs.store import ref_manager_hashes
from trame_vtkjs.widgets import VtkJsSharedView


def _view(server, offset):
    window = vtkRenderWindow()
    window.SetOffScreenRendering(1)
    handles = populate_quad(None, window)
    points = handles["polydata"].GetPoints()
    points.SetPoint(0, offset, 0, 0)
    points.Modified()
    view = VtkJsSharedView(window, trame_server=server)
    return view, window, handles["polydata"]


def _assert_picture(api, window, data):
    manager = api.vtk_object_manager
    picture = api.scene_resync(manager.GetId(window))
    node = picture["nodes"][str(manager.GetId(data))]
    points = node["arrays"]["points"]
    actual = np.frombuffer(picture["blobs"][points["ref"]], dtype=np.float32)
    np.testing.assert_array_equal(
        actual, vtk_to_numpy(data.GetPoints().GetData()).ravel()
    )
    return points["ref"]


def test_closed_first_view_does_not_poison_later_frame_cleanup(monkeypatch, capfd):
    server = get_server("window-lifecycle", client_type="vue3")
    first = _view(server, 10)
    second = _view(server, 20)
    api = first[0].api
    monkeypatch.setattr(api, "addAttachment", lambda value: bytes(value))
    old_ref = _assert_picture(api, first[1], first[2])
    (old_hash,) = ref_manager_hashes([old_ref])
    third = None
    try:
        first[0].close()
        first[1].Finalize()
        del first
        gc.collect()
        third = _view(server, 30)

        api.flush_stale_blobs()
        assert "There is no state" not in capfd.readouterr().err
        assert api.vtk_object_manager.GetBlob(old_hash).GetNumberOfValues() == 0
        _assert_picture(api, second[1], second[2])
        _assert_picture(api, third[1], third[2])

        for frame in range(1, 5):
            with second[0].transaction():
                points = second[2].GetPoints()
                points.SetPoint(1, frame, frame, 0)
                points.Modified()
            second[0].sync()
            api.flush_stale_blobs()
            assert "There is no state" not in capfd.readouterr().err
            _assert_picture(api, second[1], second[2])
            _assert_picture(api, third[1], third[2])
    finally:
        second[0].close()
        second[1].Finalize()
        if third is not None:
            third[0].close()
            third[1].Finalize()


def _cloud_view(server):
    window = vtkRenderWindow()
    window.SetOffScreenRendering(1)
    renderer = vtkRenderer()
    window.AddRenderer(renderer)
    coordinates = np.linspace(0, 1, 30_000, dtype=np.float32).reshape(-1, 3)
    points = vtkPoints()
    points.SetData(numpy_to_vtk(coordinates, deep=True))
    vertices = vtkCellArray()
    vertices.InsertNextCell(1)
    vertices.InsertCellPoint(0)
    data = vtkPolyData()
    data.SetPoints(points)
    data.SetVerts(vertices)
    add_actor(renderer, data)
    return VtkJsSharedView(window, trame_server=server), window, data


def test_view_changes_retire_serialized_snapshots_of_retained_frames(monkeypatch):
    server = get_server("window-lifecycle-retained-frames", client_type="vue3")
    live = _cloud_view(server)
    api = live[0].api
    monkeypatch.setattr(api, "addAttachment", lambda value: bytes(value))
    points = live[2].GetPoints()
    try:
        for frame in range(3):
            points.SetPoint(42, frame + 2, 3, 4)
            points.Modified()
            live[0].sync()
        api.flush_stale_blobs()
        memory = []
        for frame in range(6):
            points.SetPoint(42, frame + 20, 3, 4)
            points.Modified()
            live[0].sync()
            temporary = _view(server, frame + 100)
            temporary[0].close()
            temporary[1].Finalize()
            del temporary
            gc.collect()
            api.flush_stale_blobs()
            _assert_picture(api, live[1], live[2])
            memory.append(api.vtk_object_manager.GetTotalBlobMemoryUsage())
        assert memory == [memory[0]] * len(memory)
    finally:
        live[0].close()
        live[1].Finalize()
