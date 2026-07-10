from mcp.server.fastmcp import FastMCP

from autocad_mcp.state import get_controller


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def save_drawing(file_path: str) -> str:
        """将当前图纸另存为指定路径。"""
        get_controller().save_drawing(file_path)
        return f"saved to {file_path}"
