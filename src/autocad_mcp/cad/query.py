"""Entity/layer query + edit capabilities — the gap the reference project
(CAD-MCP) does not cover: it can only create entities, never read or modify
existing ones.
"""

import math

import pythoncom
import win32com.client

from autocad_mcp.cad.connection import CADConnection, CADDocumentChangedError
from autocad_mcp.cad.execution import invoke_mutator
from autocad_mcp.cad.geometry import Point, to_variant_point

# ObjectName（ActiveX 类名）到 DXF group-0 类型名的映射，只收录这个项目实际会画出来的
# 类型，且都是拿真实 AutoCAD 连接一个个实测验证过的（DXF 类型名不能直接从 ObjectName
# 猜，比如 AcDbBlockReference 对应的是 "INSERT" 不是 "BLOCKREFERENCE"）。query_entities
# 按类型过滤时，命中这个表就交给 AutoCAD 内部的 SelectionSet 过滤（见 devlog #11），
# 不在表里的类型名回退到原来的全表扫描，不会因为没收录就查不到。
_ENTITY_TYPE_TO_DXF_FILTER = {
    "AcDbLine": "LINE",
    "AcDbCircle": "CIRCLE",
    "AcDbArc": "ARC",
    "AcDb2dPolyline": "POLYLINE",
    "AcDbText": "TEXT",
    "AcDbMText": "MTEXT",
    "AcDbHatch": "HATCH",
    "AcDbBlockReference": "INSERT",
    "AcDbAlignedDimension": "DIMENSION",
}


class _NativeSummaryReader:
    """Read-only DISPIDs cached for ONE canonical object's lifetime.

    Never cache property values or reuse another object's wrapper/type map.
    GetIDsOfNames guarantees IDs for the object's lifetime (MS Automation).
    """

    def __init__(self, ole):
        self.ole, self.ids = ole, {}

    def dispid(self, name):
        if name not in self.ids:
            from autocad_mcp.cad.capture import retry_read

            self.ids[name] = retry_read(lambda: self.ole.GetIDsOfNames(name))
        return self.ids[name]

    def get(self, name):
        from autocad_mcp.cad.capture import retry_read, wrap

        return retry_read(
            lambda: wrap(
                self.ole.Invoke(
                    self.dispid(name), 0, pythoncom.DISPATCH_PROPERTYGET, True
                )
            )
        )

    def call(self, name, *args):
        if name not in {"GetBulge", "GetAttributes"}:
            raise ValueError("Summary methods are read-only")
        from autocad_mcp.cad.capture import retry_read, wrap

        return retry_read(
            lambda: wrap(
                self.ole.Invoke(
                    self.dispid(name), 0, pythoncom.DISPATCH_METHOD, True, *args
                )
            )
        )

    def bounds(self):
        from autocad_mcp.cad.capture import retry_read

        return retry_read(
            lambda: self.ole.InvokeTypes(
                self.dispid("GetBoundingBox"),
                0,
                pythoncom.DISPATCH_METHOD,
                (pythoncom.VT_VOID, 0),
                (
                    (pythoncom.VT_BYREF | pythoncom.VT_VARIANT, 2),
                    (pythoncom.VT_BYREF | pythoncom.VT_VARIANT, 2),
                ),
            )
        )


def _entity_summary(entity, readers=None, raw_dispatch=False) -> dict:
    reader = None
    ole = entity if raw_dispatch else getattr(entity, "_oleobj_", None)
    object_id = None
    if ole is not None:
        from autocad_mcp.cad.capture import retry_read

        token = ole.QueryInterface(pythoncom.IID_IUnknown)
        readers = readers if readers is not None else {}
        object_id = retry_read(
            lambda: ole.Invoke(
                ole.GetIDsOfNames("ObjectID"), 0, pythoncom.DISPATCH_PROPERTYGET, True
            )
        )
        cached = readers.get(object_id)
        if cached is not None and CADConnection._same(cached[0], token):
            reader = cached[1]
        else:
            reader = _NativeSummaryReader(ole)
            readers[object_id] = (token, reader)
    get = reader.get if reader else lambda name: getattr(entity, name)
    summary = {
        "object_id": object_id if reader else get("ObjectID"),
        "type": get("ObjectName"),
        "layer": get("Layer"),
    }
    try:
        if summary["type"] in {
            "AcDb2dPolyline",
            "AcDbPolyline",
            "AcDbText",
            "AcDbMText",
        }:
            raise AttributeError("This native class exposes other geometry fields")
        summary["start_point"] = list(get("StartPoint"))
        summary["end_point"] = list(get("EndPoint"))
    except Exception:
        pass
    try:
        if summary["type"] in {
            "AcDb2dPolyline",
            "AcDbPolyline",
            "AcDbText",
            "AcDbMText",
        }:
            raise AttributeError("This native class exposes other geometry fields")
        summary["center"] = list(get("Center"))
        summary["radius"] = get("Radius")
    except Exception:
        pass
    try:
        if summary["type"] in {"AcDb2dPolyline", "AcDbPolyline"}:
            raise AttributeError("Native polyline is not TEXT")
        summary["text_string"] = get("TextString")
    except Exception:
        pass
    try:
        min_point, max_point = reader.bounds() if reader else entity.GetBoundingBox()
        summary["bounding_box"] = {"min": list(min_point), "max": list(max_point)}
    except Exception:
        pass
    try:
        if summary["type"] == "AcDbBlockReference":
            summary["block_name"] = get("EffectiveName")
            summary["insertion_point"] = list(get("InsertionPoint"))
            summary["rotation"] = math.degrees(get("Rotation"))
            if get("HasAttributes"):
                attrs = (
                    reader.call("GetAttributes") if reader else entity.GetAttributes()
                )
                summary["attributes"] = {a.TagString: a.TextString for a in attrs}
    except Exception:
        pass
    # Additive native geometry evidence; a bounding box cannot verify vertices.
    if summary["type"] in {"AcDb2dPolyline", "AcDbPolyline"}:
        try:
            summary["coordinates"] = list(get("Coordinates"))
            summary["coordinate_dimension"] = (
                3 if summary["type"] == "AcDb2dPolyline" else 2
            )
            summary["closed"] = bool(get("Closed"))
            summary["normal"] = list(get("Normal"))
            summary["elevation"] = float(get("Elevation"))
            summary["constant_width"] = float(get("ConstantWidth"))
            vertices = len(summary["coordinates"]) // summary["coordinate_dimension"]
            get_bulge = (
                (lambda i: reader.call("GetBulge", i)) if reader else entity.GetBulge
            )
            summary["bulges"] = [float(get_bulge(i)) for i in range(vertices)]
        except (AttributeError, pythoncom.com_error):
            pass
    if summary["type"] == "AcDbText":
        for key, name in [
            ("height", "Height"),
            ("scale_factor", "ScaleFactor"),
            ("rotation_radians", "Rotation"),
            ("insertion_point", "InsertionPoint"),
        ]:
            try:
                value = get(name)
                summary[key] = list(value) if isinstance(value, tuple) else value
            except (AttributeError, pythoncom.com_error):
                pass
    return summary


class CADQuery:
    def __init__(self, connection: CADConnection):
        self.connection = connection
        self._summary_document = None
        self._summary_readers = {}

    def _readers(self):
        current = CADConnection._native_identity(self.connection.document)
        if self._summary_document is None or not CADConnection._same(
            current, self._summary_document
        ):
            self._summary_document = current
            self._summary_readers.clear()
        return self._summary_readers

    def _summaries(self, collection, entity_type=None):
        readers = self._readers()
        ole = getattr(collection, "_oleobj_", None)
        if ole is None:
            return [
                _entity_summary(e, readers)
                for e in collection
                if not entity_type or e.ObjectName == entity_type
            ]
        from autocad_mcp.cad.capture import prop, retry_read

        # Raw IDispatch iteration avoids per-entity dynamic wrapper/type-map
        # construction. Resolve collection metadata once; read every value fresh.
        count = prop(collection, "Count")
        item = retry_read(lambda: ole.GetIDsOfNames("Item"))
        result = []
        for i in range(count):
            entity = retry_read(
                lambda i=i: ole.Invoke(item, 0, pythoncom.DISPATCH_METHOD, True, i)
            )
            summary = _entity_summary(entity, readers, raw_dispatch=True)
            if not entity_type or summary["type"] == entity_type:
                result.append(summary)
        return result

    def list_layers(self) -> list[str]:
        from autocad_mcp.cad.capture import prop, retry_read

        layers = prop(self.connection.document, "Layers")
        ole = getattr(layers, "_oleobj_", None)
        if ole is None:
            return [layer.Name for layer in layers]
        # Dynamic collection wrappers can retain an exhausted/stale enumerator
        # after Layers.Add. Fetch Count/Item/Name afresh, just as for ModelSpace;
        # neither the enumerator nor property values are reusable observations.
        count = prop(layers, "Count")
        item = retry_read(lambda: ole.GetIDsOfNames("Item"))
        result = []
        for index in range(count):
            layer = retry_read(
                lambda index=index: ole.Invoke(
                    item, 0, pythoncom.DISPATCH_METHOD, True, index
                )
            )
            result.append(
                _NativeSummaryReader(getattr(layer, "_oleobj_", layer)).get("Name")
            )
        return result

    def _model_space(self):
        # Fetch a fresh ModelSpace reference each time rather than reusing
        # connection.model_space: pywin32's dynamic dispatch caches the
        # collection's enumerator on the wrapper object, which goes stale
        # (raises a generic com_error) after the collection is modified
        # (e.g. an entity deleted) or iterated more than once.
        return self.connection.document.ModelSpace

    def _find_entity(self, object_id: int):
        # Document.ObjectIdToObject 是 O(1) 直接查找，实测比全表扫描 ModelSpace 快
        # 几百倍（1500 个实体的图纸里，扫描到中间要 3.4s，ObjectIdToObject 只要
        # 0.0045s，见 devlog #11）。
        try:
            from autocad_mcp.cad.capture import method, prop

            entity = method(self.connection.document, "ObjectIdToObject")(object_id)
            if getattr(entity, "_oleobj_", None) is not None or hasattr(
                entity, "Document"
            ):
                owner = prop(entity, "Document")
                if self.connection.document_id(owner) != self.connection.document_id(
                    self.connection.document
                ):
                    raise CADDocumentChangedError(
                        "Entity belongs to another document; no mutation dispatched"
                    )
            return entity
        except pythoncom.com_error as exc:
            raise KeyError(f"未找到 ObjectID={object_id} 的实体") from exc

    def query_entities(self, entity_type: str | None = None) -> list[dict]:
        dxf_filter = (
            _ENTITY_TYPE_TO_DXF_FILTER.get(entity_type) if entity_type else None
        )
        if dxf_filter:
            # 按类型过滤时，交给 AutoCAD 原生的 SelectionSet 类型过滤，避免 Python
            # 侧对每个不匹配的实体都要发一次 COM 调用查 ObjectName——大图纸场景实测
            # 有数量级的速度差（1650 个实体里挑 150 个圆：79s -> 11s，见 devlog #11）。
            document = self.connection.document
            sel_set_name = "_MCP_TYPE_QUERY"
            try:
                document.SelectionSets.Item(sel_set_name).Delete()
            except Exception:
                pass
            sel_set = document.SelectionSets.Add(sel_set_name)
            try:
                filter_type = win32com.client.VARIANT(
                    pythoncom.VT_ARRAY | pythoncom.VT_I2, [0]
                )
                filter_data = win32com.client.VARIANT(
                    pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, [dxf_filter]
                )
                # 和 query_entities_in_region 一样的规避：第一次 Select 偶发返回空集合。
                sel_set.Select(5, None, None, filter_type, filter_data)
                sel_set.Select(5, None, None, filter_type, filter_data)
                return self._summaries(sel_set)
            finally:
                sel_set.Delete()

        return self._summaries(self._model_space(), entity_type)

    def query_entities_in_region(
        self,
        corner1: Point,
        corner2: Point,
        mode: str = "crossing",
        entity_type: str | None = None,
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
            sel_set.Select(
                mode_map[mode], to_variant_point(*corner1), to_variant_point(*corner2)
            )
            sel_set.Select(
                mode_map[mode], to_variant_point(*corner1), to_variant_point(*corner2)
            )
            results = []
            for entity in sel_set:
                if entity_type and entity.ObjectName != entity_type:
                    continue
                results.append(_entity_summary(entity, self._readers()))
            return results
        finally:
            sel_set.Delete()

    def get_entity(self, object_id: int) -> dict:
        return _entity_summary(self._find_entity(object_id), self._readers())

    def delete_entity(self, object_id: int) -> None:
        invoke_mutator(self._find_entity(object_id), "Delete")

    def move_entity(self, object_id: int, offset: Point) -> None:
        """把实体沿 offset 向量平移（不是移动到绝对坐标，是相对位移）。"""
        entity = self._find_entity(object_id)
        invoke_mutator(
            entity, "Move", to_variant_point(0, 0, 0), to_variant_point(*offset)
        )

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

    def scale_entity(
        self, object_id: int, base_point: Point, scale_factor: float
    ) -> None:
        """以 base_point 为基点等比缩放。"""
        entity = self._find_entity(object_id)
        entity.ScaleEntity(to_variant_point(*base_point), scale_factor)

    def mirror_entity(
        self, object_id: int, point1: Point, point2: Point, erase_source: bool = False
    ) -> int:
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
        self,
        object_ids: list[int] | None = None,
        block_name: str | None = None,
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
            results[entity.ObjectID] = {
                a.TagString: a.TextString for a in entity.GetAttributes()
            }
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
                results.append(
                    {
                        "object_id": object_id,
                        "tag": tag,
                        "status": "error",
                        "error": str(e),
                    }
                )
        return results

    def validate_block_attributes(
        self, required_tags: list[str], block_name: str | None = None
    ) -> list[dict]:
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
                problems.append(
                    {
                        "object_id": entity.ObjectID,
                        "block_name": entity.EffectiveName,
                        "missing_tags": missing,
                        "empty_tags": empty,
                    }
                )
        return problems
