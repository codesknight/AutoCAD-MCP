from mcp.server.fastmcp import FastMCP

from autocad_mcp.state import get_controller


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def draw_line(
        start_x: float, start_y: float, start_z: float,
        end_x: float, end_y: float, end_z: float,
        layer: str = "",
    ) -> str:
        """在当前图纸中画一条直线，返回新实体的 ObjectID。"""
        object_id = get_controller().draw_line(
            (start_x, start_y, start_z), (end_x, end_y, end_z), layer or None
        )
        return f"draw_line ok, object_id={object_id}"

    @mcp.tool()
    def draw_circle(center_x: float, center_y: float, center_z: float, radius: float, layer: str = "") -> str:
        """在当前图纸中画一个圆，返回新实体的 ObjectID。"""
        object_id = get_controller().draw_circle((center_x, center_y, center_z), radius, layer or None)
        return f"draw_circle ok, object_id={object_id}"

    @mcp.tool()
    def draw_arc(
        center_x: float, center_y: float, center_z: float, radius: float,
        start_angle: float, end_angle: float, layer: str = "",
    ) -> str:
        """画一段圆弧，起止角度单位为度（从 X 轴正方向逆时针计），返回新实体的 ObjectID。"""
        object_id = get_controller().draw_arc(
            (center_x, center_y, center_z), radius, start_angle, end_angle, layer or None
        )
        return f"draw_arc ok, object_id={object_id}"

    @mcp.tool()
    def draw_rectangle(
        corner1_x: float, corner1_y: float, corner1_z: float,
        corner2_x: float, corner2_y: float, corner2_z: float,
        layer: str = "",
    ) -> str:
        """画一个矩形（对角两点确定），返回新实体的 ObjectID。"""
        object_id = get_controller().draw_rectangle(
            (corner1_x, corner1_y, corner1_z), (corner2_x, corner2_y, corner2_z), layer or None
        )
        return f"draw_rectangle ok, object_id={object_id}"

    @mcp.tool()
    def draw_text(
        position_x: float, position_y: float, position_z: float,
        text: str, height: float, layer: str = "", rotation: float = 0.0,
    ) -> str:
        """在指定位置插入文字（rotation 单位为度），返回新实体的 ObjectID。"""
        object_id = get_controller().draw_text(
            (position_x, position_y, position_z), text, height, layer or None, rotation
        )
        return f"draw_text ok, object_id={object_id}"

    @mcp.tool()
    def draw_polyline(points: list[list[float]], closed: bool = False, layer: str = "") -> str:
        """画一条多段线，points 是 [x,y,z] 坐标点的列表，返回新实体的 ObjectID。"""
        object_id = get_controller().draw_polyline([tuple(p) for p in points], closed, layer or None)
        return f"draw_polyline ok, object_id={object_id}"

    @mcp.tool()
    def draw_hatch(points: list[list[float]], pattern_name: str = "SOLID", layer: str = "") -> str:
        """对 points 围成的闭合边界填充图案（默认 SOLID 实体填充），返回新实体的 ObjectID。"""
        object_id = get_controller().draw_hatch([tuple(p) for p in points], pattern_name, layer or None)
        return f"draw_hatch ok, object_id={object_id}"

    @mcp.tool()
    def add_dimension(
        start_x: float, start_y: float, start_z: float,
        end_x: float, end_y: float, end_z: float,
        text_x: float, text_y: float, text_z: float,
    ) -> str:
        """添加一个对齐标注（起点、终点、标注文字位置），返回新实体的 ObjectID。"""
        object_id = get_controller().add_dimension(
            (start_x, start_y, start_z), (end_x, end_y, end_z), (text_x, text_y, text_z)
        )
        return f"add_dimension ok, object_id={object_id}"

    @mcp.tool()
    def draw_mtext(
        position_x: float, position_y: float, position_z: float,
        text: str, width: float = 100.0, height: float = 2.5, layer: str = "",
    ) -> str:
        """插入多行富文本（支持 \\n 换行，超出 width 会自动换行），返回新实体的 ObjectID。"""
        object_id = get_controller().draw_mtext(
            (position_x, position_y, position_z), text, width, height, layer or None
        )
        return f"draw_mtext ok, object_id={object_id}"

    @mcp.tool()
    def insert_block(
        block_name: str, position_x: float, position_y: float, position_z: float,
        scale: float = 1.0, rotation: float = 0.0, layer: str = "",
    ) -> str:
        """插入一个图块引用（比如标准电力设备符号），返回新实体的 ObjectID。
        block_name 可以是当前图纸已有的图块名（用 list_blocks 查），也可以是一个 .dwg 文件的
        完整路径（AutoCAD 会自动把它定义成同名图块）。rotation 单位为度。
        """
        object_id = get_controller().insert_block(
            block_name, (position_x, position_y, position_z), scale, rotation, layer or None
        )
        return f"insert_block ok, object_id={object_id}"

    @mcp.tool()
    def create_layer(name: str, color: int | None = None) -> str:
        """新建图层。color 是 AutoCAD 颜色索引（ACI，1=红 2=黄 3=绿 4=青 5=蓝 6=洋红 7=白/黑），
        不填用默认颜色。"""
        get_controller().create_layer(name, color)
        return f"create_layer ok, name={name}"

    @mcp.tool()
    def set_layer_properties(
        name: str, color: int | None = None, locked: bool | None = None,
        frozen: bool | None = None, visible: bool | None = None,
    ) -> str:
        """修改已有图层的颜色/锁定/冻结/可见性，不填的参数保持不变。"""
        get_controller().set_layer_properties(name, color, locked, frozen, visible)
        return f"set_layer_properties ok, name={name}"
