"""Entity/layer query capabilities — the gap the reference project (CAD-MCP)
does not cover.

MVP implementation iterates ModelSpace directly (O(n)); classic AutoCAD COM
has no ObjectIdToObject like the .NET API, so this is the straightforward
approach until/unless performance on large drawings requires something smarter.
"""
from autocad_mcp.cad.connection import CADConnection


def _entity_summary(entity) -> dict:
    summary = {
        "object_id": entity.ObjectID,
        "type": entity.ObjectName,
        "layer": entity.Layer,
    }
    try:
        summary["start_point"] = list(entity.StartPoint)
        summary["end_point"] = list(entity.EndPoint)
    except Exception:
        pass
    try:
        summary["center"] = list(entity.Center)
        summary["radius"] = entity.Radius
    except Exception:
        pass
    try:
        summary["text_string"] = entity.TextString
    except Exception:
        pass
    return summary


class CADQuery:
    def __init__(self, connection: CADConnection):
        self.connection = connection

    def list_layers(self) -> list[str]:
        return [layer.Name for layer in self.connection.document.Layers]

    def _model_space(self):
        # Fetch a fresh ModelSpace reference each time rather than reusing
        # connection.model_space: pywin32's dynamic dispatch caches the
        # collection's enumerator on the wrapper object, which goes stale
        # (raises a generic com_error) after the collection is modified
        # (e.g. an entity deleted) or iterated more than once.
        return self.connection.document.ModelSpace

    def query_entities(self, entity_type: str | None = None) -> list[dict]:
        results = []
        for entity in self._model_space():
            if entity_type and entity.ObjectName != entity_type:
                continue
            results.append(_entity_summary(entity))
        return results

    def get_entity(self, object_id: int) -> dict:
        for entity in self._model_space():
            if entity.ObjectID == object_id:
                return _entity_summary(entity)
        raise KeyError(f"未找到 ObjectID={object_id} 的实体")

    def delete_entity(self, object_id: int) -> None:
        for entity in self._model_space():
            if entity.ObjectID == object_id:
                entity.Delete()
                return
        raise KeyError(f"未找到 ObjectID={object_id} 的实体")
