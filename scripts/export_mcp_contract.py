"""Export actual MCP stdio tools/list without connecting to AutoCAD.

Run from the project root: python scripts/export_mcp_contract.py --output tools.json
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def collect() -> list[dict]:
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "autocad_mcp.server"],
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            response = await session.list_tools()
            return [tool.model_dump(mode="json", exclude_none=True)
                    for tool in sorted(response.tools, key=lambda tool: tool.name)]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data = json.dumps(asyncio.run(collect()), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(data, encoding="utf-8")
    else:
        print(data, end="")

if __name__ == "__main__":
    main()
