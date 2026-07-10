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
        """画一段圆弧（TODO：下一阶段实现）。"""
        get_controller().draw_arc(
            (center_x, center_y, center_z), radius, start_angle, end_angle, layer or None
        )
        return "not implemented yet"

    @mcp.tool()
    def draw_rectangle(
        corner1_x: float, corner1_y: float, corner1_z: float,
        corner2_x: float, corner2_y: float, corner2_z: float,
        layer: str = "",
    ) -> str:
        """画一个矩形（TODO：下一阶段实现）。"""
        get_controller().draw_rectangle(
            (corner1_x, corner1_y, corner1_z), (corner2_x, corner2_y, corner2_z), layer or None
        )
        return "not implemented yet"

    @mcp.tool()
    def draw_text(position_x: float, position_y: float, position_z: float, text: str, height: float, layer: str = "") -> str:
        """插入文字（TODO：下一阶段实现）。"""
        get_controller().draw_text((position_x, position_y, position_z), text, height, layer or None)
        return "not implemented yet"
