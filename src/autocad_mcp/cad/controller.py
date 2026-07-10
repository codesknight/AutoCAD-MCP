"""Drawing operations, wrapping AutoCAD ModelSpace COM methods."""
import math

from autocad_mcp.cad.connection import CADConnection
from autocad_mcp.cad.geometry import Point, to_variant_double_array, to_variant_object_array, to_variant_point


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
        """Draw a circle and return the new entity's ObjectID handle."""
        model_space = self.connection.model_space
        circle = model_space.AddCircle(to_variant_point(*center), radius)
        if layer:
            circle.Layer = layer
        return circle.ObjectID

    def draw_arc(
        self, center: Point, radius: float, start_angle: float, end_angle: float,
        layer: str | None = None,
    ) -> int:
        """start_angle/end_angle 单位为度，从 X 轴正方向逆时针计。"""
        model_space = self.connection.model_space
        arc = model_space.AddArc(
            to_variant_point(*center), radius, math.radians(start_angle), math.radians(end_angle)
        )
        if layer:
            arc.Layer = layer
        return arc.ObjectID

    def _add_polyline(self, points: list[Point], closed: bool = False, layer: str | None = None):
        model_space = self.connection.model_space
        flat = [coord for point in points for coord in point]
        polyline = model_space.AddPolyline(to_variant_double_array(flat))
        polyline.Closed = closed
        if layer:
            polyline.Layer = layer
        return polyline

    def draw_polyline(self, points: list[Point], closed: bool = False, layer: str | None = None) -> int:
        return self._add_polyline(points, closed, layer).ObjectID

    def draw_rectangle(self, corner1: Point, corner2: Point, layer: str | None = None) -> int:
        x1, y1, z = corner1
        x2, y2, _ = corner2
        points = [(x1, y1, z), (x2, y1, z), (x2, y2, z), (x1, y2, z)]
        return self.draw_polyline(points, closed=True, layer=layer)

    def draw_text(self, position: Point, text: str, height: float, layer: str | None = None, rotation: float = 0.0) -> int:
        """rotation 单位为度。"""
        model_space = self.connection.model_space
        text_obj = model_space.AddText(text, to_variant_point(*position), height)
        if rotation:
            text_obj.Rotation = math.radians(rotation)
        if layer:
            text_obj.Layer = layer
        return text_obj.ObjectID

    def draw_hatch(self, points: list[Point], pattern_name: str = "SOLID", layer: str | None = None) -> int:
        """用 points 围成的闭合多段线作为边界填充图案（1 = acHatchPatternTypePreDefined）。"""
        model_space = self.connection.model_space
        boundary = self._add_polyline(points, closed=True)
        hatch = model_space.AddHatch(1, pattern_name, True)
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

    def save_drawing(self, file_path: str) -> None:
        self.connection.document.SaveAs(file_path)
