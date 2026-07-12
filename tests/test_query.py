"""cad/query.py 的查询/编辑能力，跑在真实 AutoCAD 连接的空白 scratch 图纸上。"""
import pytest
import win32com.client

from autocad_mcp.cad.controller import CADController
from autocad_mcp.cad.query import CADQuery


def test_query_entities_no_filter(scratch_doc):
    ctrl = CADController(scratch_doc)
    query = CADQuery(scratch_doc)
    ctrl.draw_line((0, 0, 0), (10, 10, 0))
    ctrl.draw_circle((0, 0, 0), 5)
    assert len(query.query_entities()) == 2


def test_query_entities_type_filter(scratch_doc):
    ctrl = CADController(scratch_doc)
    query = CADQuery(scratch_doc)
    ctrl.draw_line((0, 0, 0), (10, 10, 0))
    oid_circle = ctrl.draw_circle((0, 0, 0), 5)

    circles = query.query_entities("AcDbCircle")
    assert [r["object_id"] for r in circles] == [oid_circle]


def test_query_entities_unmapped_type_falls_back(scratch_doc):
    """不在 DXF 过滤映射表里的类型名要能正确回退到全表扫描，而不是查不到/报错。"""
    ctrl = CADController(scratch_doc)
    query = CADQuery(scratch_doc)
    ctrl.draw_line((0, 0, 0), (10, 10, 0))
    assert query.query_entities("AcDbSomeUnmappedType") == []


def test_get_entity_and_delete_entity(scratch_doc):
    ctrl = CADController(scratch_doc)
    query = CADQuery(scratch_doc)
    oid = ctrl.draw_circle((1, 2, 0), 3)

    info = query.get_entity(oid)
    assert info["center"] == [1.0, 2.0, 0.0]
    assert info["radius"] == 3

    query.delete_entity(oid)
    with pytest.raises(KeyError):
        query.get_entity(oid)


def test_get_entity_nonexistent_raises_keyerror(scratch_doc):
    query = CADQuery(scratch_doc)
    with pytest.raises(KeyError):
        query.get_entity(999999999999)


def test_move_rotate_copy_scale_mirror(scratch_doc):
    ctrl = CADController(scratch_doc)
    query = CADQuery(scratch_doc)
    oid = ctrl.draw_line((0, 0, 0), (10, 0, 0))

    query.move_entity(oid, (5, 5, 0))
    assert query.get_entity(oid)["start_point"] == [5.0, 5.0, 0.0]

    query.rotate_entity(oid, (5, 5, 0), 90)
    end_point = query.get_entity(oid)["end_point"]
    assert end_point[0] == pytest.approx(5.0, abs=1e-6)

    copy_id = query.copy_entity(oid, (100, 0, 0))
    assert copy_id != oid
    assert query.get_entity(copy_id) is not None

    query.scale_entity(copy_id, (105, 5, 0), 2.0)

    mirror_id = query.mirror_entity(oid, (0, 0, 0), (0, 1, 0))
    assert mirror_id != oid
    assert query.get_entity(mirror_id) is not None


def test_query_entities_in_region_crossing_vs_outside(scratch_doc):
    ctrl = CADController(scratch_doc)
    query = CADQuery(scratch_doc)
    oid_inside = ctrl.draw_line((10, 10, 0), (20, 20, 0))
    oid_outside = ctrl.draw_line((200, 200, 0), (250, 250, 0))

    result = query.query_entities_in_region((0, 0, 0), (60, 60, 0))
    ids = [r["object_id"] for r in result]
    assert oid_inside in ids
    assert oid_outside not in ids


def test_query_entities_in_region_invalid_mode_raises(scratch_doc):
    query = CADQuery(scratch_doc)
    with pytest.raises(ValueError):
        query.query_entities_in_region((0, 0, 0), (10, 10, 0), mode="bogus")


def _make_attributed_block(scratch_doc, block_name):
    doc = scratch_doc.document
    origin = win32com.client.VARIANT(win32com.client.pythoncom.VT_ARRAY | win32com.client.pythoncom.VT_R8, [0, 0, 0])
    blk_def = doc.Blocks.Add(origin, block_name)
    blk_def.AddAttribute(2.5, 0, "Enter ID:", origin, "DEVICE_ID", "DEFAULT")


def test_block_attributes_single_get_set(scratch_doc):
    ctrl = CADController(scratch_doc)
    query = CADQuery(scratch_doc)
    _make_attributed_block(scratch_doc, "PYTEST_ATTR_BLOCK_1")
    oid = ctrl.insert_block("PYTEST_ATTR_BLOCK_1", (0, 0, 0))

    assert query.get_block_attributes(oid) == {"DEVICE_ID": "DEFAULT"}

    query.set_block_attribute(oid, "DEVICE_ID", "BRK-001")
    assert query.get_block_attributes(oid) == {"DEVICE_ID": "BRK-001"}

    with pytest.raises(KeyError):
        query.set_block_attribute(oid, "NO_SUCH_TAG", "x")


def test_bulk_block_attributes_and_validate(scratch_doc):
    ctrl = CADController(scratch_doc)
    query = CADQuery(scratch_doc)
    _make_attributed_block(scratch_doc, "PYTEST_ATTR_BLOCK_2")
    oid1 = ctrl.insert_block("PYTEST_ATTR_BLOCK_2", (0, 0, 0))
    oid2 = ctrl.insert_block("PYTEST_ATTR_BLOCK_2", (300, 0, 0))

    bulk_result = query.bulk_get_block_attributes(block_name="PYTEST_ATTR_BLOCK_2")
    assert set(bulk_result.keys()) == {oid1, oid2}

    updates = [
        {"object_id": oid1, "tag": "DEVICE_ID", "value": "BRK-A"},
        {"object_id": 999999999999, "tag": "DEVICE_ID", "value": "SHOULD_FAIL"},
    ]
    results = query.bulk_set_block_attributes(updates)
    assert results[0]["status"] == "ok"
    assert results[1]["status"] == "error"
    assert query.get_block_attributes(oid1) == {"DEVICE_ID": "BRK-A"}

    query.set_block_attribute(oid2, "DEVICE_ID", "")
    problems = query.validate_block_attributes(
        ["DEVICE_ID", "NONEXISTENT_TAG"], block_name="PYTEST_ATTR_BLOCK_2"
    )
    by_id = {p["object_id"]: p for p in problems}
    assert by_id[oid1]["missing_tags"] == ["NONEXISTENT_TAG"]
    assert by_id[oid1]["empty_tags"] == []
    assert by_id[oid2]["empty_tags"] == ["DEVICE_ID"]
