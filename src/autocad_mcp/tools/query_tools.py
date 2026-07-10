import json

from mcp.server.fastmcp import FastMCP

from autocad_mcp.state import get_query


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def list_layers() -> str:
        """列出当前图纸的所有图层名（JSON 数组）。"""
        return json.dumps(get_query().list_layers(), ensure_ascii=False)

    @mcp.tool()
    def query_entities(entity_type: str = "") -> str:
        """查询当前图纸中的实体，可选按类型（如 AcDbLine/AcDbCircle）过滤，返回结构化 JSON。"""
        return json.dumps(get_query().query_entities(entity_type or None), ensure_ascii=False)

    @mcp.tool()
    def get_entity(object_id: int) -> str:
        """按 ObjectID 获取单个实体详情。"""
        return json.dumps(get_query().get_entity(object_id), ensure_ascii=False)

    @mcp.tool()
    def delete_entity(object_id: int) -> str:
        """按 ObjectID 删除实体。"""
        get_query().delete_entity(object_id)
        return f"deleted object_id={object_id}"
