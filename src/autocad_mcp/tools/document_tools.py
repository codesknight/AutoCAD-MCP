from mcp.server.fastmcp import FastMCP

from autocad_mcp.state import get_controller


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def save_drawing(file_path: str) -> str:
        """将当前图纸另存为指定路径。"""
        get_controller().save_drawing(file_path)
        return f"saved to {file_path}"

    @mcp.tool()
    def export_current_view(file_path: str = "") -> str:
        """把当前 AutoCAD 图纸的全图导出成 PNG 图片，方便交给看图工具
        （比如 ask_drawing_vqa）分析。不填 file_path 会自动生成一个临时文件路径。
        返回实际导出的图片路径。
        """
        return get_controller().export_current_view(file_path or None)
