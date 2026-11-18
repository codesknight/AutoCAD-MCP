"""共用 fixture。真实 AutoCAD 连接类测试遵循 CLAUDE.md 的安全规则：连不上就
pytest.skip 而不是报错失败；scratch_doc 每次都强制切到一张全新空白图纸，
绝不会在用户当前打开的真实图纸上跑测试。
"""
import pytest

from autocad_mcp.cad.connection import CADConnection, CADConnectionError


@pytest.fixture(scope="session")
def cad_connection():
    conn = CADConnection()
    try:
        conn.connect()
    except CADConnectionError as exc:
        pytest.skip(f"AutoCAD 未运行或连接失败，跳过：{exc}")
    return conn


@pytest.fixture
def scratch_doc(cad_connection):
    cad_connection.new_document()
    return cad_connection


def pytest_addoption(parser):
    parser.addoption("--cad-integration", action="store_true", default=False,
                     help="Enable tests that can launch AutoCAD and create scratch drawings")


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "cad_connection" in item.fixturenames:
            item.add_marker(pytest.mark.cad_integration)
        if item.get_closest_marker("cad_integration") and not config.getoption("--cad-integration"):
            item.add_marker(pytest.mark.skip(reason="Use --cad-integration for real AutoCAD tests"))
