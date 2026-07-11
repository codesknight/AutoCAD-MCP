"""Drawing operations, wrapping AutoCAD ModelSpace COM methods."""
import math
import os
import tempfile
import time
import uuid

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

    def export_current_view(self, file_path: str | None = None, timeout: float = 30.0) -> str:
        """把当前图纸的全图导出成光栅图片（用 AutoCAD 自带的
        PublishToWeb PNG.pc3 光栅打印驱动），给 VQA 等看图工具用。
        不给 file_path 就自动在系统临时目录生成一个，返回实际用的路径。
        完成后把布局的打印配置改回原样，不持久修改用户的图纸设置。
        `PlotToFile` 是异步的（调用后立刻返回，文件在后台慢慢写），
        所以要轮询等文件出现并且大小稳定下来才算真正导出完成。
        """
        if not file_path:
            export_dir = os.path.join(tempfile.gettempdir(), "autocad_mcp_exports")
            os.makedirs(export_dir, exist_ok=True)
            file_path = os.path.join(export_dir, f"{uuid.uuid4().hex}.png")

        doc = self.connection.document
        self.connection.app.ZoomExtents()

        layout = doc.ActiveLayout
        # A layout that has never been plotted has an empty ConfigName --
        # assigning that back is itself an invalid COM call, so only restore
        # when there was actually a prior device configured.
        original_config = layout.ConfigName
        try:
            layout.ConfigName = "PublishToWeb PNG.pc3"
            # Switching plot device leaves the old paper size/media assigned,
            # which silently breaks the plot job unless refreshed explicitly.
            # RefreshPlotDeviceInfo() picks a sane default media itself (this
            # device's media names are pixel-resolution presets like
            # "FHD_(1920.00_x_1080.00_Pixels)", not a generic "MaxSize").
            layout.RefreshPlotDeviceInfo()
            # RefreshPlotDeviceInfo() defaults to PlotRotation=1 (90°) to
            # best-fit the drawing extents to the media aspect ratio, which
            # sideways-rotates the whole image -- force upright output since
            # a rotated engineering drawing is harder for a VQA model to read.
            layout.PlotRotation = 0
            layout.PlotType = 1  # acExtents
            layout.CenterPlot = True
            doc.Plot.PlotToFile(file_path)
            self._wait_for_stable_file(file_path, timeout)
        finally:
            if original_config:
                layout.ConfigName = original_config
                layout.RefreshPlotDeviceInfo()
        return file_path

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
