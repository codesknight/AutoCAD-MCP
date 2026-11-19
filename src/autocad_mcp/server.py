from contextlib import asynccontextmanager

import anyio

from mcp.server.fastmcp import FastMCP

from autocad_mcp.tools import document_tools, drawing_tools, query_tools, reference_tools, vqa_tools, runtime_tools

from autocad_mcp.state import server_session_started, server_session_stopped


@asynccontextmanager
async def lifespan(server):
    server_session_started()
    try:
        yield {}
    finally:
        # MCP session task groups cancel during disconnect; finish shared cleanup.
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(server_session_stopped)


mcp = FastMCP("autocad-mcp", host="127.0.0.1", port=8931, lifespan=lifespan)

drawing_tools.register(mcp)
query_tools.register(mcp)
document_tools.register(mcp)
vqa_tools.register(mcp)
reference_tools.register(mcp)
runtime_tools.register(mcp)

if __name__ == "__main__":
    import sys

    if "--http" in sys.argv:
        # Used by web/backend (a standalone MCP client) so the Claude Desktop
        # stdio path in claude_desktop_config.json is untouched.
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
