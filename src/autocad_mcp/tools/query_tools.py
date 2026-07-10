from mcp.server.fastmcp import FastMCP

from autocad_mcp.state import get_query


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def list_layers() -> str:
        """列出当前图纸的所有图层（TODO：下一阶段实现，是本项目相对参考项目的创新点之一）。"""
        get_query().list_layers()
        return "not implemented yet"

    @mcp.tool()
    def query_entities(entity_type: str = "") -> str:
        """查询当前图纸中的实体（TODO：下一阶段实现）。"""
        get_query().query_entities(entity_type or None)
        return "not implemented yet"
