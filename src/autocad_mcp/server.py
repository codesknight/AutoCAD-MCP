from mcp.server.fastmcp import FastMCP

from autocad_mcp.tools import document_tools, drawing_tools, query_tools

mcp = FastMCP("autocad-mcp")

drawing_tools.register(mcp)
query_tools.register(mcp)
document_tools.register(mcp)

if __name__ == "__main__":
    mcp.run()
