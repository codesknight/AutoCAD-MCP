from mcp.server.fastmcp import FastMCP

from autocad_mcp.state import get_controller


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def save_drawing(file_path: str) -> str:
        """保存当前图纸到指定路径（TODO：下一阶段实现）。"""
        get_controller().save_drawing(file_path)
        return "not implemented yet"
