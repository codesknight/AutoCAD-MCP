"""Entity/layer query capabilities — the gap the reference project (CAD-MCP)
does not cover. Skeleton only; implement in a later pass.
"""
from autocad_mcp.cad.connection import CADConnection


class CADQuery:
    def __init__(self, connection: CADConnection):
        self.connection = connection

    def list_layers(self) -> list[str]:
        raise NotImplementedError("TODO: 下一阶段实现")

    def query_entities(self, entity_type: str | None = None) -> list[dict]:
        raise NotImplementedError("TODO: 下一阶段实现")

    def get_entity(self, object_id: int) -> dict:
        raise NotImplementedError("TODO: 下一阶段实现")

    def delete_entity(self, object_id: int) -> None:
        raise NotImplementedError("TODO: 下一阶段实现")
