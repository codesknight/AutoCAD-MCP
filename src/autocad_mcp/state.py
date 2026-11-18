"""Lazy process-wide backend and compatibility accessors; no native objects escape."""
import atexit
from threading import RLock

from autocad_mcp.config import load_config
from autocad_mcp.cad.backends.base import (
    CadBackend, OperationFacade, CONTROLLER_OPERATIONS, QUERY_OPERATIONS,
)
from autocad_mcp.cad.backends.factory import create_backend

_lock = RLock()
_backend: CadBackend | None = None
_controller: OperationFacade | None = None
_query: OperationFacade | None = None
_server_sessions = 0


def get_backend() -> CadBackend:
    global _backend
    with _lock:
        if _backend is None:
            _backend = create_backend(load_config())
        return _backend


def get_controller() -> OperationFacade:
    global _controller
    with _lock:
        if _controller is None:
            _controller = OperationFacade(get_backend(), CONTROLLER_OPERATIONS)
        return _controller


def get_query() -> OperationFacade:
    global _query
    with _lock:
        if _query is None:
            _query = OperationFacade(get_backend(), QUERY_OPERATIONS)
        return _query


def new_document() -> str:
    return get_backend().execute("new_document", {})


def analyze_reference_drawing(file_path: str, entity_type: str | None = None,
                              max_entities: int = 500) -> dict:
    return get_backend().execute("analyze_reference_drawing", {
        "file_path": file_path, "entity_type": entity_type, "max_entities": max_entities,
    })


def close_backend() -> None:
    """Drain and close; the next accessor explicitly starts a fresh backend.

    Existing facade references stay closed rather than silently switching target.
    This never saves/closes documents, quits CAD, or replays a failed operation.
    """
    global _backend, _controller, _query
    with _lock:
        if _backend is not None:
            _backend.close()
        _backend = _controller = _query = None


def server_session_started() -> None:
    """FastMCP low-level lifespan is per client session for HTTP transport."""
    global _server_sessions
    with _lock:
        _server_sessions += 1


def server_session_stopped() -> None:
    """Only the final client session may close the shared backend."""
    global _server_sessions
    with _lock:
        _server_sessions -= 1
        if _server_sessions == 0:
            close_backend()


atexit.register(close_backend)
