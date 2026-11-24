"""Foreground plotting and full restoration, independent of real AutoCAD."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from autocad_mcp.cad.capture import CADCaptureError
from autocad_mcp.cad.controller import CADController


class Layout:
    def __init__(self):
        self.Name = "Model"
        self.ConfigName = ""
        self.ModelType = True
        self.CenterPlot = False
        self.PlotType = 0
        self.PlotRotation = 1
        self.UseStandardScale = False
        self.StandardScale = 16
        self.CanonicalMediaName = "original media"
        self.window = ((0, 0), (1, 1))
        self.deleted = False
        self.PaperUnits = 1
        self.PlotOrigin = (0.0, 0.0)

    def CopyFrom(self, other):
        for name, value in vars(other).items():
            if name not in ("deleted", "Name", "Delete"):
                setattr(self, name, deepcopy(value))

    def RefreshPlotDeviceInfo(self):
        self.CanonicalMediaName = "PNG media"

    def Delete(self):
        self.deleted = True

    def SetWindowToPlot(self, low, high):
        self.window = (tuple(low.value), tuple(high.value))

    def GetWindowToPlot(self):
        return self.window

    def GetCustomScale(self):
        return (1, 1)


@pytest.mark.parametrize("failure", [None, "plot_false", "timeout", "plot_error"])
@pytest.mark.parametrize("unresolved_add", [False, True])
def test_foreground_capture_restores_all_settings(tmp_path, failure, unresolved_add):
    layout, backup = Layout(), Layout()
    before = vars(layout).copy()
    variables = {"BACKGROUNDPLOT": 3, "EXTMIN": (0, 0, 0), "EXTMAX": (10, 10, 0)}
    path = tmp_path / "capture.png"
    calls = []
    plot = SimpleNamespace(QuietErrorMode=False)

    def plot_to_file(target):
        calls.append("plot")
        assert variables["BACKGROUNDPLOT"] == 0
        assert plot.QuietErrorMode
        assert layout.StandardScale == 0 and layout.UseStandardScale
        assert layout.PlotType == 4 and layout.PlotRotation == 0
        assert layout.window == ((-0.5, -0.5), (10.5, 10.5))
        if failure == "plot_error":
            raise RuntimeError("native plot failure")
        path.write_bytes(b"synthetic only")
        return failure != "plot_false"

    plot.PlotToFile = plot_to_file
    adds = []

    def add(name, _model):
        adds.append(name)
        backup.Name = name
        return SimpleNamespace() if unresolved_add else backup

    class Configurations:
        Add = staticmethod(add)
        Item = staticmethod(lambda key: backup)

        @property
        def Count(self):
            return int(bool(adds) and not backup.deleted)

    doc = SimpleNamespace(Name="fixture.dwg", ActiveLayout=layout, Plot=plot,
                          ModelSpace=SimpleNamespace(Count=1), Regen=lambda _mode: None,
                          Utility=SimpleNamespace(TranslateCoordinates=lambda point, *_args: tuple(point.value)),
                          PlotConfigurations=Configurations(),
                          GetVariable=lambda key: variables[key],
                          SetVariable=lambda key, value: variables.__setitem__(key, value))
    ctrl = CADController(SimpleNamespace(document=doc))

    def wait(*_args):
        if failure == "timeout":
            raise TimeoutError("synthetic timeout")

    ctrl._wait_for_stable_file = wait
    if failure:
        with pytest.raises((RuntimeError, TimeoutError)):
            ctrl.export_current_view(str(path))
    else:
        assert ctrl.export_current_view(str(path)) == str(path)
    assert vars(layout) == before
    assert backup.deleted is (failure != "plot_error")
    assert variables["BACKGROUNDPLOT"] == 3
    assert not plot.QuietErrorMode
    assert calls == ["plot"]
    assert len(adds) == 1


@pytest.mark.parametrize("failure", ["unready", "restore"])
def test_backup_failure_preserves_first_error_and_restores_other_state(tmp_path, monkeypatch, failure):
    class Unready(Layout):
        def __getattribute__(self, name):
            if name in ("CopyFrom", "Delete"):
                raise AttributeError("snapshot." + name)
            return super().__getattribute__(name)

    class CannotRestore(Layout):
        def CopyFrom(self, other):
            raise RuntimeError("layout restore failed")

    layout = CannotRestore() if failure == "restore" else Layout()
    backup = Layout() if failure == "restore" else Unready()
    variables, sets, adds = {"BACKGROUNDPLOT": 3}, [], []
    plot = SimpleNamespace(QuietErrorMode=False, PlotToFile=lambda _path: True)

    def add(name, _model):
        adds.append(name)
        backup.Name = name
        return SimpleNamespace()

    def set_variable(key, value):
        sets.append((key, value))
        variables[key] = value

    class Configurations:
        Add = staticmethod(add)
        Item = staticmethod(lambda key: backup)

        @property
        def Count(self):
            return int(bool(adds) and not backup.deleted)

    doc = SimpleNamespace(Name="fixture.dwg", ActiveLayout=layout, Plot=plot, ModelSpace=SimpleNamespace(Count=0),
                          Regen=lambda _mode: None,
                          PlotConfigurations=Configurations(),
                          GetVariable=lambda key: variables[key], SetVariable=set_variable)
    monkeypatch.setattr("autocad_mcp.cad.controller.time.sleep", lambda _seconds: None)
    ctrl = CADController(SimpleNamespace(document=doc))
    ctrl._wait_for_stable_file = lambda *_args: None
    with pytest.raises(CADCaptureError) as error:
        ctrl.export_current_view(str(tmp_path / "capture.png"))
    assert len(adds) == 1
    assert variables["BACKGROUNDPLOT"] == 3
    assert not plot.QuietErrorMode
    assert not backup.deleted  # failed layout restore retains its recovery copy
    if failure == "unready":
        assert not sets  # Failed backup readiness never changed runtime variables.
        assert "snapshot.CopyFrom" in str(error.value)
        assert "snapshot.Delete" in str(error.value.evidence["restoration_errors"])
    else:
        assert sets[-1] == ("BACKGROUNDPLOT", 3)
        assert "layout restore failed" in str(error.value.evidence["restoration_errors"])


def test_existing_capture_target_refused_before_native_state_changes(tmp_path):
    path = tmp_path / "existing.png"
    path.write_bytes(b"keep")
    ctrl = CADController(None)
    with pytest.raises(FileExistsError):
        ctrl.export_current_view(str(path))
    assert path.read_bytes() == b"keep"
