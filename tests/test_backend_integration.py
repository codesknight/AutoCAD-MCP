"""Explicit opt-in smoke for the STA backend, using a new scratch drawing only."""
import asyncio
import json
import sys

import pytest
import win32com.client

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from autocad_mcp import state
from autocad_mcp.config import load_config

pytestmark = pytest.mark.cad_integration


def test_sta_backend_create_query_and_reconnect():
    # Attach-only preflight: skip rather than auto-launching CAD in this smoke.
    try:
        win32com.client.GetActiveObject(load_config().prog_id)
    except Exception as exc:
        pytest.skip(f"Start AutoCAD before the STA smoke: {exc}")
    state.close_backend()
    try:
        query = state.get_query()  # query-first regression, read-only before new_drawing
        query.list_layers()
        document = state.new_document()
        print(f"STA smoke writes only to newly created scratch: {document}")
        controller = state.get_controller()
        controller.create_layer("MCP_BACKEND_SMOKE", color=1)
        line = controller.draw_line((0, 0, 0), (10, 0, 0), "MCP_BACKEND_SMOKE")
        circle = controller.draw_circle((20, 0, 0), 5, "MCP_BACKEND_SMOKE")
        assert query.get_entity(line)["start_point"] == [0.0, 0.0, 0.0]
        assert query.get_entity(circle)["radius"] == 5
        assert {row["object_id"] for row in query.query_entities()} == {line, circle}
        state.close_backend()
        assert state.get_query().get_entity(line)["layer"] == "MCP_BACKEND_SMOKE"
    finally:
        state.close_backend()


def test_real_mcp_stdio_create_and_query():
    try:
        win32com.client.GetActiveObject(load_config().prog_id)
    except Exception as exc:
        pytest.skip(f"Start AutoCAD before the MCP smoke: {exc}")
    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "autocad_mcp.server"])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                assert len((await client.list_tools()).tools) == 44
                async def call(name, arguments):
                    result = await client.call_tool(name, arguments)
                    assert not result.isError, result.content
                    return result.structuredContent["result"]
                await call("list_layers", {})  # Query-first, no writes to initial drawing.
                document = await call("new_drawing", {})
                print(f"MCP smoke writes only to newly created scratch: {document}")
                await call("draw_line", {"start_x":0,"start_y":0,"start_z":0,
                                         "end_x":10,"end_y":0,"end_z":0})
                entities = json.loads(await call("query_entities", {}))
                assert len(entities) == 1
                assert entities[0]["start_point"] == [0.0, 0.0, 0.0]
                assert entities[0]["end_point"] == [10.0, 0.0, 0.0]
    asyncio.run(run())
