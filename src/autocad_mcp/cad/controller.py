"""Drawing operations, wrapping AutoCAD ModelSpace COM methods.

Only draw_line is fully implemented for now (proof of the end-to-end
scaffold). Everything else is a stub for the next development pass —
see docs/logs/devlog.md for the TODO list.
"""
from autocad_mcp.cad.connection import CADConnection
from autocad_mcp.cad.geometry import Point, to_variant_point


class CADController:
    def __init__(self, connection: CADConnection):
        self.connection = connection

    def draw_line(self, start: Point, end: Point, layer: str | None = None) -> int:
        """Draw a line and return the new entity's ObjectID handle."""
        model_space = self.connection.model_space
        line = model_space.AddLine(to_variant_point(*start), to_variant_point(*end))
        if layer:
            line.Layer = layer
        return line.ObjectID

    def draw_circle(self, center: Point, radius: float, layer: str | None = None) -> int:
        raise NotImplementedError("TODO: 下一阶段实现")

    def draw_arc(
        self, center: Point, radius: float, start_angle: float, end_angle: float,
        layer: str | None = None,
    ) -> int:
        raise NotImplementedError("TODO: 下一阶段实现")

    def draw_polyline(self, points: list[Point], closed: bool = False, layer: str | None = None) -> int:
        raise NotImplementedError("TODO: 下一阶段实现")

    def draw_rectangle(self, corner1: Point, corner2: Point, layer: str | None = None) -> int:
        raise NotImplementedError("TODO: 下一阶段实现")

    def draw_text(self, position: Point, text: str, height: float, layer: str | None = None) -> int:
        raise NotImplementedError("TODO: 下一阶段实现")

    def draw_hatch(self, points: list[Point], pattern_name: str = "SOLID", layer: str | None = None) -> int:
        raise NotImplementedError("TODO: 下一阶段实现")

    def add_dimension(self, start: Point, end: Point, text_position: Point) -> int:
        raise NotImplementedError("TODO: 下一阶段实现")

    def save_drawing(self, file_path: str) -> None:
        raise NotImplementedError("TODO: 下一阶段实现")
