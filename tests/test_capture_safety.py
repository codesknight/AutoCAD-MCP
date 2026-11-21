"""Foreground plotting and full restoration, independent of real AutoCAD."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from autocad_mcp.cad.controller import CADController


class Layout:
    def __init__(self):
        self.ConfigName = ""
        self.ModelType = True
        self.CenterPlot = False
        self.PlotType = 0
        self.PlotRotation = 1
        self.UseStandardScale = False
        self.StandardScale = 16
        self.CanonicalMediaName = "original media"
        self.deleted = False

    def CopyFrom(self, other):
        for name, value in vars(other).items():
            if name != "deleted":
                setattr(self, name, deepcopy(value))

    def RefreshPlotDeviceInfo(self):
        self.CanonicalMediaName = "PNG media"

    def Delete(self):
        self.deleted = True


@pytest.mark.parametrize("failure", [None, "plot_false", "timeout", "plot_error"])
def test_foreground_capture_restores_all_settings(tmp_path, failure):
    layout, backup = Layout(), Layout()
    before = vars(layout).copy()
    variables = {"BACKGROUNDPLOT": 3}
    path = tmp_path / "capture.png"
    calls = []
    plot = SimpleNamespace(QuietErrorMode=False)

    def plot_to_file(target):
        calls.append("plot")
        assert variables["BACKGROUNDPLOT"] == 0
        assert plot.QuietErrorMode
        assert layout.StandardScale == 0 and layout.UseStandardScale
        assert layout.PlotType == 1 and layout.PlotRotation == 0
        if failure == "plot_error":
            raise RuntimeError("native plot failure")
        path.write_bytes(b"synthetic only")
        return failure != "plot_false"

    plot.PlotToFile = plot_to_file
    doc = SimpleNamespace(ActiveLayout=layout, Plot=plot,
                          PlotConfigurations=SimpleNamespace(Add=lambda *_args: backup),
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
    assert backup.deleted
    assert variables["BACKGROUNDPLOT"] == 3
    assert not plot.QuietErrorMode
    assert calls == ["plot"]


def test_existing_capture_target_refused_before_native_state_changes(tmp_path):
    path = tmp_path / "existing.png"
    path.write_bytes(b"keep")
    ctrl = CADController(None)
    with pytest.raises(FileExistsError):
        ctrl.export_current_view(str(path))
    assert path.read_bytes() == b"keep"
