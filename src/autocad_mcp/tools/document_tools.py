from mcp.server.fastmcp import FastMCP

from autocad_mcp import state
from autocad_mcp.state import get_controller


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def new_drawing() -> str:
        """新建一张空白图纸并切换过去（不会碰当前正在编辑的图纸），
        返回新图纸的名字。做实验性的绘图操作前建议先调用这个，
        避免不小心画到用户正在编辑的真实图纸上。
        """
        return state.new_document()

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
