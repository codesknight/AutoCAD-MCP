"""Real MCP JSON-RPC tests with fake CAD; no external CAD/VQA/model calls."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from autocad_mcp import state
from autocad_mcp.server import mcp

FIXTURES = Path(__file__).parent / "fixtures"
TOOLS = json.loads((FIXTURES / "mcp-tools-v0.1.json").read_text(encoding="utf-8"))
CALLS = json.loads((FIXTURES / "mcp-calls-v0.1.json").read_text(encoding="utf-8"))


def stable_schema(tool):
    return {key: tool[key] for key in ("name", "description", "inputSchema", "outputSchema")}


def normalized(value):
    # Coordinate tuples in Python intentionally correspond to JSON arrays.
    return json.loads(json.dumps(value))


def test_actual_stdio_tool_discovery_matches_baseline(tmp_path):
    target = tmp_path / "tools.json"
    subprocess.run([sys.executable, "scripts/export_mcp_contract.py", "--output", str(target)],
                   cwd=Path(__file__).resolve().parents[1], check=True, timeout=30,
                   capture_output=True)
    actual = json.loads(target.read_text(encoding="utf-8"))
    assert [stable_schema(tool) for tool in actual] == [stable_schema(tool) for tool in TOOLS]


@pytest.mark.parametrize("case", CALLS, ids=lambda row: row["tool"])
def test_legacy_tool_arguments_and_results_over_mcp(case, monkeypatch):
    calls = []
    class Backend:
        def execute(self, operation, payload):
            calls.append((operation, normalized(payload)))
            return case["result"]
        def close(self): pass
    state.close_backend()
    monkeypatch.setattr(state, "create_backend", lambda _: Backend())
    async def run():
        async with create_connected_server_and_client_session(mcp) as client:
            response = await client.call_tool(case["tool"], case["arguments"])
            assert not response.isError
            assert [item.text for item in response.content] == [case["text"]]
            assert response.structuredContent == {"result": case["text"]}
    try:
        asyncio.run(run())
        assert calls == [(case["operation"], case["payload"])]
    finally:
        state.close_backend()


def test_invalid_mcp_arguments_never_reach_backend(monkeypatch):
    def forbidden(*args):
        pytest.fail("Invalid MCP input must not create a backend")
    state.close_backend()
    monkeypatch.setattr(state, "create_backend", forbidden)
    async def run():
        async with create_connected_server_and_client_session(mcp) as client:
            response = await client.call_tool("draw_circle", {"center_x":0,"center_y":0,"center_z":0})
            assert response.isError
    asyncio.run(run())


def test_one_client_disconnect_cannot_close_another_clients_backend(monkeypatch):
    events = []
    class Backend:
        closed = False
        def execute(self, operation, payload):
            assert not self.closed, "Another client disconnected and closed our backend"
            return ["0"]
        def close(self):
            self.closed = True
            events.append("close")
    state.close_backend()
    monkeypatch.setattr(state, "create_backend", lambda _: Backend())
    async def run():
        async with create_connected_server_and_client_session(mcp) as first:
            assert not (await first.call_tool("list_layers", {})).isError
            async with create_connected_server_and_client_session(mcp) as second:
                assert not (await second.call_tool("list_layers", {})).isError
            assert events == []
            assert not (await first.call_tool("list_layers", {})).isError
        assert events == ["close"]
    try:
        asyncio.run(run())
    finally:
        state.close_backend()
