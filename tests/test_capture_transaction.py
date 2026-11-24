"""Capture readiness, uncertain restoration and correlated MCP receipts."""
import asyncio
from types import SimpleNamespace

import pytest
import pythoncom
from autocad_mcp import state
from autocad_mcp.cad import capture
from autocad_mcp.cad.capture import CADCaptureError
from autocad_mcp.cad.controller import CADController
from autocad_mcp.tools.document_tools import register
from mcp.server.fastmcp import FastMCP
from test_capture_safety import Layout


def fixture(tmp_path):
    layout, configs, calls = Layout(), {}, []
    variables = {"BACKGROUNDPLOT": 3}
    path = tmp_path / "capture.png"

    def add(name, _model):
        calls.append("add")
        backup = Layout()
        backup.Name = name
        backup.Delete = lambda: configs.pop(name)
        configs[name] = backup
        return SimpleNamespace()

    class Configurations:
        Add = staticmethod(add)
        Item = staticmethod(lambda key: list(configs.values())[key] if isinstance(key, int) else configs[key])

        @property
        def Count(self):
            return len(configs)

    plot = SimpleNamespace(QuietErrorMode=False, PlotToFile=lambda _: calls.append("plot") or True)
    doc = SimpleNamespace(Name="fixture.dwg", ActiveLayout=layout, Plot=plot,
                          ModelSpace=SimpleNamespace(Count=0), PlotConfigurations=Configurations(),
                          Regen=lambda _: calls.append("regen"),
                          GetVariable=lambda key: variables[key],
                          SetVariable=lambda key, value: variables.__setitem__(key, value))
    ctrl = CADController(SimpleNamespace(document=doc))
    ctrl._wait_for_stable_file = lambda *_: None
    return ctrl, doc, configs, calls, path


@pytest.mark.parametrize("transient", [True, False])
def test_count_read_retries_precede_all_plot_changes(tmp_path, monkeypatch, transient):
    ctrl, doc, configs, calls, path = fixture(tmp_path)
    monkeypatch.setattr(capture.time, "sleep", lambda _: None)

    class Space:
        attempts = 0

        @property
        def Count(self):
            self.attempts += 1
            assert doc.ActiveLayout.ConfigName == "" and not configs
            if self.attempts == 1 or not transient:
                raise AttributeError("<unknown>.Count")
            return 0
    doc.ModelSpace = Space()
    if transient:
        assert ctrl.export_current_view(str(path)) == str(path)
        assert doc.ModelSpace.attempts == 2
        assert calls.count("add") == calls.count("plot") == 1
    else:
        with pytest.raises(CADCaptureError) as caught:
            ctrl.export_current_view(str(path), request_id="count")
        assert not caught.value.evidence["capture_mutations_started"]
        assert caught.value.evidence["stage"] == "preflight"
        assert caught.value.evidence["actions"] == []
        assert not calls and not configs


@pytest.mark.parametrize("failure", ["invoke", "silent", "background"])
def test_restore_must_read_back_and_never_drop_unverified_backup(tmp_path, monkeypatch, failure):
    ctrl, doc, configs, calls, path = fixture(tmp_path)
    monkeypatch.setattr(capture.time, "sleep", lambda _: None)
    restores = []

    class Broken(Layout):
        def __getattribute__(self, name):
            if name == "CopyFrom" and failure == "lookup" and self.ConfigName:
                raise AttributeError("<unknown>.CopyFrom")
            return super().__getattribute__(name)

        def CopyFrom(self, other):
            restores.append(1)
            if failure == "invoke":
                raise RuntimeError("RPC_E_CALL_REJECTED")
            if failure != "silent":
                super().CopyFrom(other)
    doc.ActiveLayout = Broken()
    if failure == "background":
        original = doc.SetVariable
        def set_variable(key, value):
            if value == 3:
                raise RuntimeError("RPC_E_CALL_REJECTED")
            original(key, value)
        doc.SetVariable = set_variable
    with pytest.raises(CADCaptureError) as caught:
        ctrl.export_current_view(str(path), request_id="restore")
    assert not caught.value.evidence["restoration_verified"]
    assert caught.value.evidence["backup_name"] in configs
    assert len(restores) <= 1
    assert calls.count("add") == calls.count("plot") == 1


def test_restore_method_prebound_before_dynamic_map_becomes_unavailable(tmp_path):
    ctrl, doc, configs, calls, path = fixture(tmp_path)

    class Unstable(Layout):
        def __getattribute__(self, name):
            if name == "CopyFrom" and self.ConfigName:
                raise AttributeError("<unknown>.CopyFrom")
            return super().__getattribute__(name)
    doc.ActiveLayout = Unstable()
    value=ctrl.export_current_view(str(path),request_id="prebound")
    assert value["capture"]["restoration_verified"] and not configs
    assert calls.count("plot")==1


def test_raw_dispatch_bypasses_dynamic_count_and_copyfrom_method_maps():
    class Ole:
        def GetIDsOfNames(self, name):
            return name

        def Invoke(self, name, _locale, flags, _result, *args):
            if name == "Count":
                assert flags == pythoncom.DISPATCH_PROPERTYGET
                return 51
            assert name == "CopyFrom" and flags == pythoncom.DISPATCH_METHOD
            return args
    obj = SimpleNamespace(_oleobj_=Ole())
    assert capture.prop(obj, "Count") == 51
    assert capture.method(obj, "CopyFrom")("backup") == ("backup",)


def test_plot_snapshot_supplies_explicit_native_byref_output_arguments():
    values={name:0 for name in capture.FIELDS}
    values.update(ConfigName="device",CanonicalMediaName="media",PlotOrigin=(0.0,0.0))

    class Ole:
        def GetIDsOfNames(self, name):
            return name

        def Invoke(self, name, _locale, flags, _result, *args):
            if flags == pythoncom.DISPATCH_PROPERTYGET:
                return values[name]
            assert len(args) == 2
            if name == "GetWindowToPlot":
                args[0].value, args[1].value = (0.0,0.0), (10.0,10.0)
            else:
                assert name == "GetCustomScale"
                args[0].value, args[1].value = 1.0, 2.0
    result=capture.signature(SimpleNamespace(_oleobj_=Ole()))
    assert result["window"] == [[0.0,0.0],[10.0,10.0]]
    assert result["custom_scale"] == [1.0,2.0]


def test_layer_add_readiness_is_read_only_and_native_side_effect_is_not_replayed(monkeypatch):
    monkeypatch.setattr(capture.time, "sleep", lambda _:None)

    class Layers:
        lookups=0
        calls=0

        @property
        def Add(self):
            self.lookups+=1
            if self.lookups==1:
                raise AttributeError("<unknown>.Add")
            def add(name):
                self.calls+=1
                raise RuntimeError("native outcome unknown")
            return add
    layers=Layers()
    ctrl=CADController(SimpleNamespace(document=SimpleNamespace(Layers=layers)))
    with pytest.raises(RuntimeError,match="native outcome unknown"):
        ctrl.create_layer("test",color=1)
    assert layers.lookups==2 and layers.calls==1


def test_layout_owner_mismatch_is_rejected_before_any_capture_write(tmp_path,monkeypatch):
    ctrl,doc,configs,calls,path=fixture(tmp_path)
    doc.ActiveLayout._oleobj_=object()
    doc.ActiveLayout.ObjectID=123
    doc.ActiveLayout.Document=SimpleNamespace(Name="different-document.dwg")
    # Fake only property access; exercise the real native-ownership gate.
    monkeypatch.setattr(capture,"prop",lambda obj,name:getattr(obj,name))
    with pytest.raises(CADCaptureError) as caught:
        ctrl.export_current_view(str(path),request_id="wrong-layout-owner")
    assert "LAYOUT_OWNER_CHANGED" in str(caught.value)
    assert not caught.value.evidence["capture_mutations_started"]
    assert not calls and not configs


def test_mcp_capture_evidence_is_correlated_and_legacy_success_stays_a_string(tmp_path, monkeypatch):
    ctrl, doc, configs, calls, path = fixture(tmp_path)
    monkeypatch.setattr(state, "get_controller", lambda: ctrl)
    # document_tools imports its accessor directly.
    monkeypatch.setattr("autocad_mcp.tools.document_tools.get_controller", lambda: ctrl)
    server = FastMCP("capture-fixture")
    register(server)
    result = asyncio.run(server.call_tool("export_current_view", {"file_path": str(path), "request_id": "nonce"}))
    assert not result.isError
    assert result.structuredContent["capture"]["request_id"] == "nonce"
    assert result.structuredContent["capture"]["before"] == result.structuredContent["capture"]["after"]
    legacy = asyncio.run(server.call_tool("export_current_view", {"file_path": str(path)}))
    assert legacy.structuredContent == {"result": str(path)}
    doc.ActiveLayout.ModelType = False
    rejected = asyncio.run(server.call_tool("export_current_view", {"file_path": str(path), "request_id": "reject"}))
    assert rejected.isError and rejected.structuredContent["request_id"] == "reject"
    assert not rejected.structuredContent["capture_mutations_started"]
