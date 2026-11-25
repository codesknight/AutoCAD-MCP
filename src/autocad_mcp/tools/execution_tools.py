"""Explicit additive evidence API. Legacy tool signatures remain unchanged."""
import json
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from autocad_mcp import state
from autocad_mcp.cad.errors import UnsupportedOperationError

Identity = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")]


def response(value, error=False):
    return CallToolResult(isError=error, structuredContent=value,
                          content=[TextContent(type="text",text=json.dumps(value,ensure_ascii=False))])


def register(mcp: FastMCP):
    @mcp.tool()
    def get_document_binding() -> CallToolResult:
        """Explicitly observe the bound CAD document lifecycle identity. COM attaches only;
        this can perform native reads, unlike cached get_backend_status. Names are labels,
        revision may be unsupported/null, and reconnect invalidates the previous COM identity.
        """
        backend = state.get_backend()
        method = getattr(backend,"document_binding",None)
        if method is None:
            raise UnsupportedOperationError("Document binding observation is unavailable")
        return response(method())

    @mcp.tool()
    def execute_observed_operation(instance_id: Identity, request_id: Identity, operation: str,
                                   arguments: dict, document_id: Identity | None = None) -> CallToolResult:
        """Explicit autocad-execution/1 COM entrypoint; inspect evidence_support first.
        Uses internal CAD argument names (start/end/position/object_id, not flattened MCP names).
        new_document requires null document_id; other operations require the exact bound ID.
        Native mutators run once; ACK and later observation are separate. No atomic rollback,
        authoritative COM revision, automatic write replay or recovery after Python restart.
        HTTP clients use existing controlled document/batch/job APIs instead.
        """
        method = getattr(state.get_backend(),"execute_evidenced",None)
        if method is None:
            raise UnsupportedOperationError("Use the HTTP controlled document/batch APIs; no COM fallback")
        value = method(operation,arguments,instance_id=instance_id,request_id=request_id,document_id=document_id)
        return response(value,error=value["receipt"]["status"] == "failed")

    @mcp.tool()
    def get_execution_status(instance_id: Identity, request_id: Identity) -> CallToolResult:
        """Read the original execution record without dispatching any write. COM records live
        only in this Python backend; HTTP records belong to the Bridge. Missing/expired/foreign
        records remain unresolved and never prove that it is safe to replay a write.
        """
        method = getattr(state.get_backend(),"execution_status",None)
        if method is None:
            raise UnsupportedOperationError("Execution record lookup is unavailable")
        return response(method(instance_id,request_id))
