"""Explicit stdio cader-cad/1 revision-2 profile. Ordinary server is unchanged."""
from contextlib import asynccontextmanager
from threading import RLock
from typing import Any, Literal
import anyio
import json
from mcp.types import CallToolResult, TextContent
from mcp.server.fastmcp import FastMCP
from autocad_mcp.config import load_config
from autocad_mcp.cad.backends.http_backend import HTTPBackend
from autocad_mcp.cad.managed_contract import ManagedContractError
from autocad_mcp.cad.managed_profile import ManagedCAD

_lock=RLock()
_service=None
_sessions=0

def service():
    global _service
    with _lock:
        if _service is None:
            config=load_config()
            if config.backend!='http':
                raise ManagedContractError('HTTP_BACKEND_REQUIRED: select an explicit HTTP config; no COM fallback')
            _service=ManagedCAD(HTTPBackend(config))
        return _service

def close_service():
    global _service
    with _lock:
        if _service is not None:
            _service.backend.close()
        _service=None

def stop_session():
    global _sessions
    # Keep decrement, final-session decision and close under one lock. A new
    # client cannot inherit a service that a departing client then closes.
    with _lock:
        _sessions-=1
        if _sessions==0:close_service()

@asynccontextmanager
async def lifespan(server):
    global _sessions
    with _lock:_sessions+=1
    try:yield {}
    finally:
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(stop_session)

mcp=FastMCP('autocad-mcp-cader-cad-v1',lifespan=lifespan)

def output(value):
    # A generic dict annotation gets wrapped as {result: ...} by FastMCP.
    # The versioned contract requires the DTO itself as structuredContent.
    return CallToolResult(content=[TextContent(type='text',text=json.dumps(value,ensure_ascii=False))],structuredContent=value)


@mcp.tool()
def get_backend_status() -> CallToolResult:
    """cader-cad/1 r2: discover HTTP instance, revision mode and actual profile capabilities."""
    return output(service().get_backend_status())

@mcp.tool()
def create_working_document(instance_id: str, request_id: str, units: str, managed: Literal[True], output_directory: str) -> CallToolResult:
    """Create a writable working document bound to an existing canonical .cader/artifacts directory."""
    return output(service().create_working_document(instance_id=instance_id,request_id=request_id,units=units,managed=managed,output_directory=output_directory))

@mcp.tool()
def execute_atomic_batch(instance_id: str, request_id: str, document_id: str, expected_revision: int, operations: list[dict[str,Any]]) -> CallToolResult:
    """Execute 1–100 reviewed layer-0 line/circle/text steps with explicit identity and revision."""
    return output(service().execute_atomic_batch(instance_id=instance_id,request_id=request_id,document_id=document_id,expected_revision=expected_revision,operations=operations))

@mcp.tool()
def get_job_status(request_id: str) -> CallToolResult:
    """Read native request identity and outcome; never resubmit. Missing identity remains unresolved."""
    return output(service().get_job_status(request_id))

@mcp.tool()
def query_entities_page(instance_id: str, document_id: str, expected_revision: int, cursor: str | None, limit: int) -> CallToolResult:
    """Read a revision-bound page of canonical profile entities; unsupported attributes are explicit."""
    return output(service().query_entities_page(instance_id=instance_id,document_id=document_id,expected_revision=expected_revision,cursor=cursor,limit=limit))

@mcp.tool()
def save_document_as(instance_id: str, request_id: str, document_id: str, expected_revision: int, output_path: str, overwrite: Literal[False]) -> CallToolResult:
    """Copy-save a new DWG inside the bound output directory; files are outside entity transactions."""
    return output(service().save_document_as(instance_id=instance_id,request_id=request_id,document_id=document_id,expected_revision=expected_revision,output_path=output_path,overwrite=overwrite))

@mcp.tool()
def reopen_document(instance_id: str, request_id: str, artifact_id: str) -> CallToolResult:
    """Hash-check and independently reopen an instance-owned artifact with read-only verification binding."""
    return output(service().reopen_document(instance_id=instance_id,request_id=request_id,artifact_id=artifact_id))

if __name__=='__main__':
    import sys
    if len(sys.argv)>1:
        print('Explicit stdio profile: python -m autocad_mcp.managed_server; set AUTOCAD_MCP_CONFIG to an HTTP config')
        raise SystemExit(0 if sys.argv[1:] == ['--help'] else 2)
    mcp.run()
