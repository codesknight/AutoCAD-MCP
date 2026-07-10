"""Manual/integration test — requires a real AutoCAD instance.

Run with AutoCAD 2026 already open:
    conda run -n autocad-mcp pytest tests/test_connection.py -v -s
"""
import pytest

from autocad_mcp.cad.connection import CADConnection, CADConnectionError


def test_connect_to_running_autocad():
    conn = CADConnection()
    try:
        conn.connect()
    except CADConnectionError as exc:
        pytest.skip(f"AutoCAD 未运行或连接失败，跳过：{exc}")
    assert conn.is_connected()
    assert conn.document is not None
