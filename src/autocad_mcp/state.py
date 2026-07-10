"""Process-wide singletons wiring the cad/ layer to the tools/ layer.

Connection is established lazily on first tool call, not at import time,
so `mcp dev` / tool listing works even before AutoCAD is open.
"""
from autocad_mcp.cad.connection import CADConnection
from autocad_mcp.cad.controller import CADController
from autocad_mcp.cad.query import CADQuery

_connection: CADConnection | None = None
_controller: CADController | None = None
_query: CADQuery | None = None


def get_controller() -> CADController:
    global _connection, _controller
    if _controller is None:
        _connection = CADConnection()
        _connection.connect()
        _controller = CADController(_connection)
    return _controller


def get_query() -> CADQuery:
    global _connection, _query
    if _query is None:
        if _connection is None:
            _connection = CADConnection()
            _connection.connect()
        _query = CADQuery(_connection)
    return _query
