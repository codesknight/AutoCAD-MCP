"""Offline native-boundary negatives; real source geometry has separate evidence."""
from types import SimpleNamespace

import pytest

from autocad_mcp.cad.controller import CADController
from autocad_mcp.cad.query import _entity_summary


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_invalid_polyline_width_cannot_invoke_add(value):
    controller = CADController(SimpleNamespace())
    controller._add_polyline = lambda *_args: pytest.fail("no native creation allowed")
    with pytest.raises(ValueError, match="POLYLINE_WIDTH_INVALID"):
        controller.draw_polyline([(0, 0, 0), (1, 1, 0)], width=value)


@pytest.mark.parametrize("box", [[1, 0, 0, 1], [0, 0, 1], [0, 0, float("nan"), 1]])
def test_invalid_text_fit_is_rejected_before_style_or_creation(box):
    controller = CADController(SimpleNamespace())
    controller._ensure_cjk_text_style = lambda: pytest.fail("no dependency or native call allowed")
    with pytest.raises(ValueError, match="TEXT_FIT_BOX_INVALID"):
        controller.draw_text((0, 0, 0), "fixture", 1, fit_box=box)


def test_post_ack_fit_failure_does_not_delete_or_replay_created_text(monkeypatch):
    calls = []
    entity = SimpleNamespace(ObjectID=5)
    controller = CADController(SimpleNamespace(model_space=SimpleNamespace(
        AddText=lambda *_args: (calls.append("AddText"), entity)[1])))
    controller._ensure_cjk_text_style = lambda: "fixture"
    controller._configure_entity = lambda obj, *_args, **_kw: obj
    controller._fit_created_text = lambda *_args: (_ for _ in ()).throw(RuntimeError("fit read failed"))
    with pytest.raises(RuntimeError, match="fit read failed"):
        controller.draw_text((0, 0, 0), "fixture", 1, fit_box=[0, 0, 2, 2])
    assert calls == ["AddText"]


def test_polyline_query_retains_ocs_instead_of_pretending_bbox_is_vertices():
    entity = SimpleNamespace(ObjectID=3, ObjectName="AcDb2dPolyline", Layer="0",
                             Coordinates=(0., 0., 0., 2., 4., 0.), Closed=False,
                             Normal=(0., 1., 0.), Elevation=2., ConstantWidth=.25,
                             GetBulge=lambda i: .1 if i else 0.)
    row = _entity_summary(entity)
    assert row["coordinate_dimension"] == 3
    assert row["coordinates"] == [0., 0., 0., 2., 4., 0.]
    assert row["normal"] == [0., 1., 0.]
    assert row["elevation"] == 2.
    assert row["constant_width"] == .25
    assert row["bulges"] == [0., .1]
