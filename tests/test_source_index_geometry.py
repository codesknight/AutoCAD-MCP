"""Offline native-boundary negatives; real source geometry has separate evidence."""

from types import SimpleNamespace

import pytest
from autocad_mcp.cad.controller import CADController
from autocad_mcp.cad.query import CADQuery, _entity_summary, _NativeSummaryReader


def test_layer_query_reads_native_count_items_and_names_after_add_without_enumerator():
    class Layer:
        def __init__(self, name, dispid):
            self.name, self.dispid = name, dispid

        def GetIDsOfNames(self, name):
            assert name == "Name"
            return self.dispid

        def Invoke(self, dispid, *_args):
            assert dispid == self.dispid
            return self.name

    class Layers:
        def __init__(self):
            self._oleobj_ = self
            self.rows = [Layer("0", 17)]

        def __iter__(self):
            pytest.fail("A cached dynamic enumerator cannot be a fresh layer query")

        def GetIDsOfNames(self, name):
            return {"Count": 1, "Item": 2}[name]

        def Invoke(self, dispid, _lcid, _kind, _result, *args):
            return len(self.rows) if dispid == 1 else self.rows[args[0]]

    layers = Layers()
    query = CADQuery(SimpleNamespace(document=SimpleNamespace(Layers=layers)))
    assert query.list_layers() == ["0"]
    layers.rows.append(Layer("NEW_LAYER", 908))
    assert query.list_layers() == ["0", "NEW_LAYER"]
    layers.rows[-1].name = "RENAMED_LAYER"
    assert query.list_layers() == ["0", "RENAMED_LAYER"]


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_invalid_polyline_width_cannot_invoke_add(value):
    controller = CADController(SimpleNamespace())
    controller._add_polyline = lambda *_args: pytest.fail("no native creation allowed")
    with pytest.raises(ValueError, match="POLYLINE_WIDTH_INVALID"):
        controller.draw_polyline([(0, 0, 0), (1, 1, 0)], width=value)


@pytest.mark.parametrize("box", [[1, 0, 0, 1], [0, 0, 1], [0, 0, float("nan"), 1]])
def test_invalid_text_fit_is_rejected_before_style_or_creation(box):
    controller = CADController(SimpleNamespace())
    controller._ensure_cjk_text_style = lambda: pytest.fail(
        "no dependency or native call allowed"
    )
    with pytest.raises(ValueError, match="TEXT_FIT_BOX_INVALID"):
        controller.draw_text((0, 0, 0), "fixture", 1, fit_box=box)


def test_post_ack_fit_failure_does_not_delete_or_replay_created_text(monkeypatch):
    calls = []
    entity = SimpleNamespace(ObjectID=5)
    controller = CADController(
        SimpleNamespace(
            model_space=SimpleNamespace(
                AddText=lambda *_args: (calls.append("AddText"), entity)[1]
            )
        )
    )
    controller._ensure_cjk_text_style = lambda: "fixture"
    controller._configure_entity = lambda obj, *_args, **_kw: obj
    controller._fit_created_text = lambda *_args: (_ for _ in ()).throw(
        RuntimeError("fit read failed")
    )
    with pytest.raises(RuntimeError, match="fit read failed"):
        controller.draw_text((0, 0, 0), "fixture", 1, fit_box=[0, 0, 2, 2])
    assert calls == ["AddText"]


def test_polyline_query_retains_ocs_instead_of_pretending_bbox_is_vertices():
    entity = SimpleNamespace(
        ObjectID=3,
        ObjectName="AcDb2dPolyline",
        Layer="0",
        Coordinates=(0.0, 0.0, 0.0, 2.0, 4.0, 0.0),
        Closed=False,
        Normal=(0.0, 1.0, 0.0),
        Elevation=2.0,
        ConstantWidth=0.25,
        GetBulge=lambda i: 0.1 if i else 0.0,
    )
    row = _entity_summary(entity)
    assert row["coordinate_dimension"] == 3
    assert row["coordinates"] == [0.0, 0.0, 0.0, 2.0, 4.0, 0.0]
    assert row["normal"] == [0.0, 1.0, 0.0]
    assert row["elevation"] == 2.0
    assert row["constant_width"] == 0.25
    assert row["bulges"] == [0.0, 0.1]


def test_native_metadata_cache_is_per_canonical_object_and_values_are_always_fresh():
    class Native:
        def __init__(self, offset):
            self.token = object()
            self.offset = offset
            self.lookups = {}
            self.names = {}
            self.values = dict(
                ObjectID=7,
                ObjectName="AcDb2dPolyline",
                Layer="0",
                Coordinates=(0.0, 0.0, 0.0, 2.0, 4.0, 0.0),
                Closed=False,
                Normal=(0.0, 0.0, 1.0),
                Elevation=0.0,
                ConstantWidth=0.25,
            )

        def QueryInterface(self, _iid):
            return self.token

        def GetIDsOfNames(self, name):
            if name not in self.values and name not in {"GetBulge", "GetBoundingBox"}:
                raise AttributeError(name)
            self.lookups[name] = self.lookups.get(name, 0) + 1
            value = (
                self.offset + list(self.values).index(name)
                if name in self.values
                else self.offset + 50 + (name == "GetBulge")
            )
            self.names[value] = name
            return value

        def Invoke(self, dispid, _lcid, _kind, _result, *args):
            name = self.names[dispid]
            return 0.0 if name == "GetBulge" else self.values[name]

        def InvokeTypes(self, *_args):
            return ((0.0, 0.0, 0.0), (2.0, 4.0, 0.0))

    readers = {}
    first = Native(100)
    one = _entity_summary(SimpleNamespace(_oleobj_=first), readers)
    first.values["ConstantWidth"] = 0.75
    two = _entity_summary(SimpleNamespace(_oleobj_=first), readers)
    assert one["constant_width"] == 0.25 and two["constant_width"] == 0.75
    assert first.lookups["ConstantWidth"] == 1
    second = Native(900)
    assert (
        _entity_summary(SimpleNamespace(_oleobj_=second), readers)["constant_width"]
        == 0.25
    )
    assert second.lookups["ConstantWidth"] == 1  # Same ObjectID, DIFFERENT IUnknown.
    with pytest.raises(ValueError, match="read-only"):
        _NativeSummaryReader(first).call("Delete")
    connection = SimpleNamespace(document=SimpleNamespace(Name="same.dwg"))
    query = CADQuery(connection)
    query._readers()[7] = "fixture"
    connection.document = SimpleNamespace(Name="same.dwg")
    assert query._readers() == {}  # Name equality never preserves identity/cache.
