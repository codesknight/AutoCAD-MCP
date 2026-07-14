"""entity_to_tool_call() 的转换逻辑，包括广告/水印文字过滤。真实实体需要真实
AutoCAD 连接（画出来再转换），纯字符串匹配逻辑（_is_ad_noise）不需要。
"""
from autocad_mcp.cad.controller import CADController
from autocad_mcp.cad.training_export import _is_ad_noise, entity_to_tool_call


def test_is_ad_noise_matches_known_phrase():
    assert _is_ad_noise("这是一张图纸，来自星欣设计图库")
    assert not _is_ad_noise("单母线分段接线")
    assert not _is_ad_noise("1QQ")  # 之前用宽泛关键词 "QQ" 时会误伤这种设备位号


def _find_by_id(scratch_doc, object_id):
    for e in scratch_doc.document.ModelSpace:
        if e.ObjectID == object_id:
            return e
    raise KeyError(object_id)


def test_entity_to_tool_call_line(scratch_doc):
    ctrl = CADController(scratch_doc)
    oid = ctrl.draw_line((0, 0, 0), (10, 5, 0))
    entity = _find_by_id(scratch_doc, oid)
    call = entity_to_tool_call(entity)
    assert call["tool"] == "draw_line"
    assert call["args"]["start_x"] == 0.0
    assert call["args"]["end_x"] == 10.0


def test_entity_to_tool_call_circle(scratch_doc):
    ctrl = CADController(scratch_doc)
    oid = ctrl.draw_circle((5, 5, 0), 3)
    entity = _find_by_id(scratch_doc, oid)
    call = entity_to_tool_call(entity)
    assert call["tool"] == "draw_circle"
    assert call["args"]["radius"] == 3


def test_entity_to_tool_call_polyline(scratch_doc):
    ctrl = CADController(scratch_doc)
    points = [(0, 0, 0), (10, 0, 0), (10, 10, 0)]
    oid = ctrl.draw_polyline(points, closed=True)
    entity = _find_by_id(scratch_doc, oid)
    call = entity_to_tool_call(entity)
    assert call["tool"] == "draw_polyline"
    assert call["args"]["closed"] is True
    assert len(call["args"]["points"]) == 3


def test_entity_to_tool_call_filters_ad_noise_text(scratch_doc):
    ctrl = CADController(scratch_doc)
    oid_noise = ctrl.draw_text((0, 0, 0), "星欣设计图库", 5)
    oid_normal = ctrl.draw_text((0, 20, 0), "单母线分段接线", 5)

    assert entity_to_tool_call(_find_by_id(scratch_doc, oid_noise)) is None

    call = entity_to_tool_call(_find_by_id(scratch_doc, oid_normal))
    assert call["tool"] == "draw_text"
    assert call["args"]["text"] == "单母线分段接线"


def test_entity_to_tool_call_filters_ad_noise_mtext(scratch_doc):
    ctrl = CADController(scratch_doc)
    oid_noise = ctrl.draw_mtext((0, 0, 0), "本图来自星欣设计图库整理", width=50, height=5)
    assert entity_to_tool_call(_find_by_id(scratch_doc, oid_noise)) is None
