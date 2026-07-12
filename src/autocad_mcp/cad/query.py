"""Entity/layer query + edit capabilities — the gap the reference project
(CAD-MCP) does not cover: it can only create entities, never read or modify
existing ones.

MVP implementation iterates ModelSpace directly (O(n)); classic AutoCAD COM
has no ObjectIdToObject like the .NET API, so this is the straightforward
approach until/unless performance on large drawings requires something smarter.
"""
import math

from autocad_mcp.cad.connection import CADConnection
from autocad_mcp.cad.geometry import Point, to_variant_point


def _entity_summary(entity) -> dict:
    summary = {
        "object_id": entity.ObjectID,
        "type": entity.ObjectName,
        "layer": entity.Layer,
    }
    try:
        summary["start_point"] = list(entity.StartPoint)
        summary["end_point"] = list(entity.EndPoint)
    except Exception:
        pass
    try:
        summary["center"] = list(entity.Center)
        summary["radius"] = entity.Radius
    except Exception:
        pass
    try:
        summary["text_string"] = entity.TextString
    except Exception:
        pass
    try:
        min_point, max_point = entity.GetBoundingBox()
        summary["bounding_box"] = {"min": list(min_point), "max": list(max_point)}
    except Exception:
        pass
    try:
        if entity.ObjectName == "AcDbBlockReference":
            summary["block_name"] = entity.EffectiveName
            summary["insertion_point"] = list(entity.InsertionPoint)
            summary["rotation"] = math.degrees(entity.Rotation)
            if entity.HasAttributes:
                summary["attributes"] = {a.TagString: a.TextString for a in entity.GetAttributes()}
    except Exception:
        pass
    return summary


class CADQuery:
    def __init__(self, connection: CADConnection):
        self.connection = connection

    def list_layers(self) -> list[str]:
        return [layer.Name for layer in self.connection.document.Layers]

    def _model_space(self):
        # Fetch a fresh ModelSpace reference each time rather than reusing
        # connection.model_space: pywin32's dynamic dispatch caches the
        # collection's enumerator on the wrapper object, which goes stale
        # (raises a generic com_error) after the collection is modified
        # (e.g. an entity deleted) or iterated more than once.
        return self.connection.document.ModelSpace

    def _find_entity(self, object_id: int):
        for entity in self._model_space():
            if entity.ObjectID == object_id:
                return entity
        raise KeyError(f"未找到 ObjectID={object_id} 的实体")

    def query_entities(self, entity_type: str | None = None) -> list[dict]:
        results = []
        for entity in self._model_space():
            if entity_type and entity.ObjectName != entity_type:
                continue
            results.append(_entity_summary(entity))
        return results

    def query_entities_in_region(
        self, corner1: Point, corner2: Point, mode: str = "crossing", entity_type: str | None = None,
    ) -> list[dict]:
        """按矩形区域查询实体，用 AutoCAD 的 SelectionSet.Select 实现（O(1) 交给
        AutoCAD 内部空间索引，不是自己算包围盒相交），复杂图纸场景比全表扫描的
        query_entities 快得多，也能真正做到"只看这个区域里有什么"。

        mode="crossing"（默认）：区域内或和边界相交的实体都算，对应 AutoCAD 默认框选行为。
        mode="window"：只有完全被区域包住的实体才算。
        """
        mode_map = {"window": 0, "crossing": 1}
        if mode not in mode_map:
            raise ValueError(f"不支持的 mode={mode!r}，可选 'window' 或 'crossing'")

        document = self.connection.document
        sel_set_name = "_MCP_REGION_QUERY"
        try:
            document.SelectionSets.Item(sel_set_name).Delete()
        except Exception:
            pass
        sel_set = document.SelectionSets.Add(sel_set_name)
        try:
            # 实测发现：一个 SelectionSet 对象的*第一次* Select() 调用偶发性地会
            # 错误返回空集合（不管 mode、不管区域里实际有没有实体），同一个 set 上
            # 紧接着再 Select 一次就总是对的——这是 COM 层某种一次性的初始化时序问题，
            # 不是坐标或参数错误。这里丢弃第一次调用的结果，只用第二次的，规避掉。
            sel_set.Select(mode_map[mode], to_variant_point(*corner1), to_variant_point(*corner2))
            sel_set.Select(mode_map[mode], to_variant_point(*corner1), to_variant_point(*corner2))
            results = []
            for entity in sel_set:
                if entity_type and entity.ObjectName != entity_type:
                    continue
                results.append(_entity_summary(entity))
            return results
        finally:
            sel_set.Delete()

    def get_entity(self, object_id: int) -> dict:
        return _entity_summary(self._find_entity(object_id))

    def delete_entity(self, object_id: int) -> None:
        self._find_entity(object_id).Delete()

    def move_entity(self, object_id: int, offset: Point) -> None:
        """把实体沿 offset 向量平移（不是移动到绝对坐标，是相对位移）。"""
        entity = self._find_entity(object_id)
        entity.Move(to_variant_point(0, 0, 0), to_variant_point(*offset))

    def rotate_entity(self, object_id: int, base_point: Point, angle: float) -> None:
        """绕 base_point 旋转，angle 单位为度。"""
        entity = self._find_entity(object_id)
        entity.Rotate(to_variant_point(*base_point), math.radians(angle))

    def copy_entity(self, object_id: int, offset: Point) -> int:
        """复制一份实体并沿 offset 平移，返回新实体的 ObjectID（原实体不变）。"""
        entity = self._find_entity(object_id)
        copy = entity.Copy()
        copy.Move(to_variant_point(0, 0, 0), to_variant_point(*offset))
        return copy.ObjectID

    def scale_entity(self, object_id: int, base_point: Point, scale_factor: float) -> None:
        """以 base_point 为基点等比缩放。"""
        entity = self._find_entity(object_id)
        entity.ScaleEntity(to_variant_point(*base_point), scale_factor)

    def mirror_entity(self, object_id: int, point1: Point, point2: Point, erase_source: bool = False) -> int:
        """以 point1-point2 连线为镜像轴，返回镜像后新实体的 ObjectID。
        erase_source=True 时删除原实体（相当于"翻转"而不是"镜像复制一份"）。
        """
        entity = self._find_entity(object_id)
        mirrored = entity.Mirror(to_variant_point(*point1), to_variant_point(*point2))
        if erase_source:
            entity.Delete()
        return mirrored.ObjectID

    def get_block_attributes(self, object_id: int) -> dict:
        """取图块引用（INSERT 实体）的属性，tag -> value。"""
        entity = self._find_entity(object_id)
        if not entity.HasAttributes:
            return {}
        return {a.TagString: a.TextString for a in entity.GetAttributes()}

    def set_block_attribute(self, object_id: int, tag: str, value: str) -> None:
        entity = self._find_entity(object_id)
        for attr in entity.GetAttributes():
            if attr.TagString == tag:
                attr.TextString = value
                return
        raise KeyError(f"图块没有名为 {tag!r} 的属性标签")

    def bulk_get_block_attributes(
        self, object_ids: list[int] | None = None, block_name: str | None = None,
    ) -> dict[int, dict[str, str]]:
        """批量取多个图块引用的属性。object_ids 指定就只查这些 ObjectID；不指定则按
        block_name 过滤（block_name 也不指定就是图纸里所有带属性的图块引用）。
        返回 {object_id: {tag: value}}，成百上千个设备图块批量校核时不用逐个调
        get_block_attributes。
        """
        id_filter = set(object_ids) if object_ids else None
        results: dict[int, dict[str, str]] = {}
        for entity in self._model_space():
            if entity.ObjectName != "AcDbBlockReference":
                continue
            if id_filter is not None and entity.ObjectID not in id_filter:
                continue
            if block_name is not None and entity.EffectiveName != block_name:
                continue
            if not entity.HasAttributes:
                continue
            results[entity.ObjectID] = {a.TagString: a.TextString for a in entity.GetAttributes()}
        return results

    def bulk_set_block_attributes(self, updates: list[dict]) -> list[dict]:
        """批量设置图块属性。updates 是 [{"object_id", "tag", "value"}, ...]；单条
        失败（比如 object_id 不存在，或图块没有这个 tag）不影响其它条，返回每条的
        执行结果（status="ok" 或 "error"+错误信息）而不是让整批调用直接抛异常中断。
        """
        results = []
        for item in updates:
            object_id = item["object_id"]
            tag = item["tag"]
            value = item["value"]
            try:
                self.set_block_attribute(object_id, tag, value)
                results.append({"object_id": object_id, "tag": tag, "status": "ok"})
            except Exception as e:
                results.append({"object_id": object_id, "tag": tag, "status": "error", "error": str(e)})
        return results

    def validate_block_attributes(self, required_tags: list[str], block_name: str | None = None) -> list[dict]:
        """校核图块属性完整性：找出缺少某个必填 tag、或该 tag 值是空字符串的图块引用。
        block_name 不指定就检查图纸里所有图块引用。只返回有问题的条目
        [{"object_id", "block_name", "missing_tags", "empty_tags"}]，没问题的不出现在结果里。
        """
        problems = []
        for entity in self._model_space():
            if entity.ObjectName != "AcDbBlockReference":
                continue
            if block_name is not None and entity.EffectiveName != block_name:
                continue
            attrs = {}
            if entity.HasAttributes:
                attrs = {a.TagString: a.TextString for a in entity.GetAttributes()}
            missing = [t for t in required_tags if t not in attrs]
            empty = [t for t in required_tags if t in attrs and not attrs[t]]
            if missing or empty:
                problems.append({
                    "object_id": entity.ObjectID,
                    "block_name": entity.EffectiveName,
                    "missing_tags": missing,
                    "empty_tags": empty,
                })
        return problems
