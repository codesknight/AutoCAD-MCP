"""Internal backend contract and compatibility facades (never MCP tools).

The operation registry is explicit. No raw connection, callable, or COM object
may pass through the execution boundary. Bridge DTOs will be a separate contract.
"""
from functools import cache
from inspect import Signature, signature
from typing import Any, Protocol

from autocad_mcp.cad.errors import UnsupportedOperationError

CONTROLLER_OPERATIONS = frozenset({
    "draw_line", "draw_circle", "draw_arc", "draw_rectangle", "draw_text",
    "draw_mtext", "draw_polyline", "draw_hatch", "add_dimension", "insert_block",
    "create_layer", "set_layer_properties", "list_blocks", "save_drawing",
    "export_current_view",
})
QUERY_OPERATIONS = frozenset({
    "list_layers", "query_entities", "query_entities_in_region", "get_entity",
    "delete_entity", "move_entity", "rotate_entity", "copy_entity", "scale_entity",
    "mirror_entity", "get_block_attributes", "set_block_attribute",
    "bulk_get_block_attributes", "bulk_set_block_attributes", "validate_block_attributes",
})
OPERATIONS = CONTROLLER_OPERATIONS | QUERY_OPERATIONS | {
    "new_document", "analyze_reference_drawing",
}

class CadBackend(Protocol):
    def execute(self, operation: str, payload: dict[str, Any]) -> Any: ...
    def capabilities(self) -> dict[str, Any]: ...
    def runtime_status(self) -> dict[str, Any]: ...
    def close(self) -> None: ...

@cache
def operation_signature(operation: str) -> Signature:
    if operation not in OPERATIONS:
        raise UnsupportedOperationError(f"Unsupported CAD operation: {operation}")
    if operation == "new_document":
        return Signature()
    # Import definitions only: no COM object is constructed here.
    if operation in CONTROLLER_OPERATIONS:
        from autocad_mcp.cad.controller import CADController
        method = getattr(CADController, operation)
    elif operation in QUERY_OPERATIONS:
        from autocad_mcp.cad.query import CADQuery
        method = getattr(CADQuery, operation)
    else:
        from autocad_mcp.cad.reference_library import analyze_reference_drawing
        method = analyze_reference_drawing
    sig = signature(method)
    return sig.replace(parameters=list(sig.parameters.values())[1:])

def copy_data(value: Any) -> Any:
    """Copy plain values, preserving legacy tuple coordinates and integer keys."""
    if value is None or type(value) in (str, bool, int, float):
        return value
    if type(value) in (list, tuple):
        return type(value)(copy_data(item) for item in value)
    if type(value) is dict:
        if any(type(key) not in (str, int) for key in value):
            raise TypeError("CAD data keys must be strings or integers")
        return {key: copy_data(item) for key, item in value.items()}
    raise TypeError(f"CAD execution accepts plain data, got {type(value).__name__}")

class OperationFacade:
    """Keep legacy method calls while concealing the backend's native objects."""
    def __init__(self, backend: CadBackend, operations: frozenset[str]):
        self._backend = backend
        self._operations = operations

    def __getattr__(self, name: str):
        if name not in self._operations:
            raise AttributeError(name)
        def invoke(*args, **kwargs):
            bound = operation_signature(name).bind(*args, **kwargs)
            return self._backend.execute(name, dict(bound.arguments))
        return invoke
