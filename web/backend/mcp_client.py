"""Process-wide MCP client connecting to the AutoCAD MCP server over
streamable-http (started separately via `python -m autocad_mcp.server --http`).

This is deliberately a real MCP client, not a direct import of autocad_mcp's
cad/tools modules -- the whole point of this layer is to keep talking to
AutoCAD through the MCP protocol, the same way Claude Desktop does.
"""
from contextlib import AsyncExitStack
from datetime import timedelta

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import Tool

AUTOCAD_MCP_URL = "http://127.0.0.1:8931/mcp"

# ask_drawing_vqa alone can take ~90-130s for a single question (local 4-bit
# quantized model). The default ClientSession.call_tool() has no explicit
# read timeout override, and the underlying streamable-http transport's
# default sse_read_timeout is 300s -- set this explicitly so a slow tool call
# doesn't get cut off by some other layer's shorter default.
TOOL_CALL_TIMEOUT = timedelta(seconds=300)

_exit_stack: AsyncExitStack | None = None
_session: ClientSession | None = None


async def get_session() -> ClientSession:
    global _exit_stack, _session
    if _session is None:
        _exit_stack = AsyncExitStack()
        read, write, _ = await _exit_stack.enter_async_context(streamablehttp_client(AUTOCAD_MCP_URL))
        _session = await _exit_stack.enter_async_context(ClientSession(read, write))
        await _session.initialize()
    return _session


async def list_tools() -> list[Tool]:
    session = await get_session()
    result = await session.list_tools()
    return result.tools


async def call_tool(name: str, arguments: dict) -> str:
    session = await get_session()
    result = await session.call_tool(name, arguments, read_timeout_seconds=TOOL_CALL_TIMEOUT)
    if result.content:
        return "\n".join(block.text for block in result.content if block.type == "text")
    return ""


async def close() -> None:
    global _exit_stack, _session
    if _exit_stack is not None:
        await _exit_stack.aclose()
    _exit_stack = None
    _session = None
