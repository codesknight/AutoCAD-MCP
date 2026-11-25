"""Drawing operations, wrapping AutoCAD ModelSpace COM methods."""
import math
import os
import time
from contextlib import contextmanager

from autocad_mcp.cad.connection import CADConnection
from autocad_mcp.cad.execution import invoke_mutator, observing_execution, set_property
from autocad_mcp.cad.geometry import (
    Point,
    to_variant_double_array,
    to_variant_object_array,
    to_variant_point,
)

_CJK_TEXT_STYLE = "MCP_CJK"
_SAVE_DRAWING_EXTENSIONS = {".dwg", ".dxf", ".dwt", ".dws"}


class CADController:
    def __init__(self, connection: CADConnection):
        self.connection = connection

    @staticmethod
    def _entity_id(entity):
        if observing_execution():
            from autocad_mcp.cad.capture import prop
            return prop(entity,"ObjectID")
        return entity.ObjectID

    def _validate_layer(self, layer: str | None) -> None:
        """Resolve dependencies before Add*: setter failures must not leave geometry."""
        if layer:
            target = self.connection.document.Layers.Item(layer)
            if target.Lock or target.Freeze:
                raise ValueError(f"CAD_LAYER_NOT_WRITABLE: {layer}")

    @contextmanager
    def _creation_scope(self):
        """Best-effort cleanup of objects returned by this call only, never Undo.

        This is not a transaction or execution receipt. A lost COM response, an
        Add* that raises without returning an object, or failed cleanup is still
        uncertain and must not be retried blindly by the caller.
        """
        created = []
        try:
            yield created
        except Exception as original:
            cleanup_errors = []
            for entity in reversed(created):
                try:
                    invoke_mutator(entity, "Delete")
                except Exception as cleanup:
                    cleanup_errors.append(str(cleanup))
            if cleanup_errors:
                raise RuntimeError(
                    f"CAD_PARTIAL_MUTATION: original={original}; "
                    f"cleanup_errors={cleanup_errors}; preserve document; do not replay"
                ) from original
            raise

    def _configure_entity(self, entity, layer: str | None = None, **properties):
        with self._creation_scope() as created:
            created.append(entity)
            for name, value in properties.items():
                set_property(entity, name, value)
            if layer:
                set_property(entity, "Layer", layer)
            if observing_execution():
                # A pure ObjectID observation failure after acknowledged setters
                # must not trigger another native mutation (Delete). Preserve
                # execution facts for explicit clients to reconcile read-only.
                created.clear()
            # Include response construction in the cleanup scope.
            _ = self._entity_id(entity)
            return entity

    def _ensure_cjk_text_style(self) -> str:
        """AutoCAD 的默认文字样式 "Standard" 用 txt.shx，这个 SHX 字体没有中文字形，
        中文会在视图里显示成一堆问号。这里 get-or-create 一个用 SimSun（支持 GB2312）
        的样式，draw_text/draw_mtext 默认都用它，避免每次画中文标注都变成 "??"。
        """
        styles = self.connection.document.TextStyles
        try:
            styles.Item(_CJK_TEXT_STYLE)
        except Exception:
            style = invoke_mutator(styles, "Add", _CJK_TEXT_STYLE)
            invoke_mutator(style, "SetFont", "SimSun", False, False, 134, 0)
        return _CJK_TEXT_STYLE

    def draw_line(self, start: Point, end: Point, layer: str | None = None) -> int:
        """Draw a line and return the new entity's ObjectID handle."""
        self._validate_layer(layer)
        model_space = self.connection.model_space
        line = invoke_mutator(model_space, "AddLine", to_variant_point(*start), to_variant_point(*end))
        return self._entity_id(self._configure_entity(line, layer))

    def draw_circle(self, center: Point, radius: float, layer: str | None = None) -> int:
        """Draw a circle and return the new entity's ObjectID handle."""
        self._validate_layer(layer)
        model_space = self.connection.model_space
        circle = invoke_mutator(model_space, "AddCircle", to_variant_point(*center), radius)
        return self._entity_id(self._configure_entity(circle, layer))

    def draw_arc(
        self, center: Point, radius: float, start_angle: float, end_angle: float,
        layer: str | None = None,
    ) -> int:
        """start_angle/end_angle 单位为度，从 X 轴正方向逆时针计。"""
        self._validate_layer(layer)
        model_space = self.connection.model_space
        arc = model_space.AddArc(
            to_variant_point(*center), radius, math.radians(start_angle), math.radians(end_angle)
        )
        return self._configure_entity(arc, layer).ObjectID

    def _add_polyline(self, points: list[Point], closed: bool = False, layer: str | None = None):
        self._validate_layer(layer)
        model_space = self.connection.model_space
        flat = [coord for point in points for coord in point]
        polyline = model_space.AddPolyline(to_variant_double_array(flat))
        return self._configure_entity(polyline, layer, Closed=closed)

    def draw_polyline(self, points: list[Point], closed: bool = False, layer: str | None = None) -> int:
        return self._add_polyline(points, closed, layer).ObjectID

    def draw_rectangle(self, corner1: Point, corner2: Point, layer: str | None = None) -> int:
        x1, y1, z = corner1
        x2, y2, _ = corner2
        points = [(x1, y1, z), (x2, y1, z), (x2, y2, z), (x1, y2, z)]
        return self.draw_polyline(points, closed=True, layer=layer)

    def draw_text(self, position: Point, text: str, height: float, layer: str | None = None, rotation: float = 0.0) -> int:
        """rotation 单位为度。"""
        self._validate_layer(layer)
        style = self._ensure_cjk_text_style()
        model_space = self.connection.model_space
        text_obj = invoke_mutator(model_space, "AddText", text, to_variant_point(*position), height)
        return self._entity_id(self._configure_entity(text_obj, layer, StyleName=style, Rotation=math.radians(rotation)))

    def draw_mtext(self, position: Point, text: str, width: float = 100.0, height: float = 2.5, layer: str | None = None) -> int:
        """多行富文本。width 是文本框宽度（超出会自动换行），height 是字高。"""
        self._validate_layer(layer)
        style = self._ensure_cjk_text_style()
        model_space = self.connection.model_space
        mtext = model_space.AddMText(to_variant_point(*position), width, text)
        return self._configure_entity(mtext, layer, StyleName=style, Height=height).ObjectID

    def list_blocks(self) -> list[str]:
        """列出当前图纸里已有的、可插入的图块定义名（排除模型/图纸空间等内部匿名块）。"""
        return [b.Name for b in self.connection.document.Blocks if not b.Name.startswith("*")]

    def insert_block(
        self, block_name: str, position: Point, scale: float = 1.0, rotation: float = 0.0,
        layer: str | None = None,
    ) -> int:
        """插入一个图块引用，返回新实体的 ObjectID。block_name 可以是当前图纸已有的图块名，
        也可以是一个 .dwg 文件的完整路径（AutoCAD 会自动把它定义成同名图块）。rotation 单位为度。
        """
        self._validate_layer(layer)
        model_space = self.connection.model_space
        block_ref = model_space.InsertBlock(
            to_variant_point(*position), block_name, scale, scale, scale, math.radians(rotation)
        )
        return self._configure_entity(block_ref, layer).ObjectID

    def create_layer(self, name: str, color: int | None = None) -> None:
        """color 是 AutoCAD 颜色索引（ACI），常用：1=红 2=黄 3=绿 4=青 5=蓝 6=洋红 7=白/黑。"""
        from autocad_mcp.cad.capture import method, prop, put
        # Resolve Add metadata read-only; never retry the native layer creation.
        layer = method(prop(self.connection.document, "Layers"), "Add")(name)
        if color is not None:
            put(layer, "Color", color)

    def set_layer_properties(
        self, name: str, color: int | None = None, locked: bool | None = None,
        frozen: bool | None = None, visible: bool | None = None,
    ) -> None:
        layer = self.connection.document.Layers.Item(name)
        if color is not None:
            layer.Color = color
        if locked is not None:
            layer.Lock = locked
        if frozen is not None:
            layer.Freeze = frozen
        if visible is not None:
            layer.LayerOn = visible

    def draw_hatch(self, points: list[Point], pattern_name: str = "SOLID", layer: str | None = None) -> int:
        """用 points 围成的闭合多段线作为边界填充图案（1 = acHatchPatternTypePreDefined）。"""
        self._validate_layer(layer)
        model_space = self.connection.model_space
        with self._creation_scope() as created:
            boundary = self._add_polyline(points, closed=True)
            created.append(boundary)
            hatch = model_space.AddHatch(1, pattern_name, True)
            created.append(hatch)
            hatch.AppendOuterLoop(to_variant_object_array([boundary]))
            hatch.Evaluate()
            if layer:
                hatch.Layer = layer
            return hatch.ObjectID

    def add_dimension(self, start: Point, end: Point, text_position: Point) -> int:
        model_space = self.connection.model_space
        dim = model_space.AddDimAligned(
            to_variant_point(*start), to_variant_point(*end), to_variant_point(*text_position)
        )
        return dim.ObjectID

    def save_drawing(self, file_path: str, overwrite: bool = False) -> None:
        """另存为指定路径。默认不允许目标路径和当前文档原始路径相同——避免不小心
        覆盖用户正在编辑的真实图纸；确实要覆盖原文件时需要显式传 overwrite=True。
        """
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in _SAVE_DRAWING_EXTENSIONS:
            raise ValueError(
                f"不支持的文件格式 {ext!r}，AutoCAD SaveAs 支持的格式: {sorted(_SAVE_DRAWING_EXTENSIONS)}"
            )
        target_dir = os.path.dirname(file_path) or "."
        if not os.path.isdir(target_dir):
            raise ValueError(f"目标目录不存在: {target_dir!r}")

        current_path = self.connection.document.FullName
        if current_path and not overwrite:
            same_file = os.path.normcase(os.path.abspath(file_path)) == os.path.normcase(os.path.abspath(current_path))
            if same_file:
                raise ValueError(
                    f"目标路径和当前文档的原始文件路径相同（{current_path!r}），"
                    "这会覆盖用户正在编辑的真实图纸。如果确实要覆盖原文件，请显式传 overwrite=True。"
                )
        invoke_mutator(self.connection.document, "SaveAs", file_path)

    def export_current_view(self, file_path: str | None = None, timeout: float = 30.0,
                            request_id: str = "") -> str | dict:
        """Export the model layout once, restoring and verifying native plot state.

        A correlated caller receives the restoration receipt as plain data.
        Legacy callers retain the successful path string.
        """
        from autocad_mcp.cad.capture import export_view
        return export_view(self.connection, file_path, timeout,
                           self._wait_for_stable_file, request_id)

    @staticmethod
    def _wait_for_stable_file(file_path: str, timeout: float) -> None:
        deadline = time.time() + timeout
        last_size = -1
        while time.time() < deadline:
            if os.path.exists(file_path):
                size = os.path.getsize(file_path)
                if size > 0 and size == last_size:
                    return
                last_size = size
            time.sleep(0.5)
        raise TimeoutError(f"等待导出文件超时：{file_path}")
