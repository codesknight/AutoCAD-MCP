from mcp.server.fastmcp import FastMCP

from autocad_mcp.tools import document_tools, drawing_tools, query_tools, vqa_tools

mcp = FastMCP("autocad-mcp", host="127.0.0.1", port=8931)

drawing_tools.register(mcp)
query_tools.register(mcp)
document_tools.register(mcp)
vqa_tools.register(mcp)

if __name__ == "__main__":
    import sys

    if "--http" in sys.argv:
        # Used by web/backend (a standalone MCP client) so the Claude Desktop
        # stdio path in claude_desktop_config.json is untouched.
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
