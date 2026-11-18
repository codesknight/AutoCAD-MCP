"""Offline lifecycle/concurrency regression tests. Never instantiate real CAD."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from autocad_mcp import state
from autocad_mcp.config import Config
from autocad_mcp.cad.backends.base import OperationFacade, CONTROLLER_OPERATIONS
from autocad_mcp.cad.backends.com_backend import COMBackend, COMSession
from autocad_mcp.cad.backends.factory import create_backend
from autocad_mcp.cad.connection import CADConnection, CADDocumentChangedError
from autocad_mcp.cad.errors import (
    BackendClosedError, BackendQueueFullError, BackendWorkerError,
    UnsupportedBackendError, UnsupportedOperationError,
)


def config(**kwargs):
    return Config(cad_type="AutoCAD", prog_id="test.only", **kwargs)


class RecordingSession:
    def __init__(self, config, events):
        self.events = events
        self.events.append(("connect", get_ident()))
        self.document = "scratch-1"

    def execute(self, operation, payload):
        self.events.append((operation, get_ident()))
        if operation == "new_document":
            self.document = "scratch-2"
            return self.document
        if operation == "draw_line":
            return 101
        if operation == "query_entities":
            return [{"document": self.document}]
        return [self.document]

    def close(self):
        self.events.append(("close", get_ident()))


@pytest.fixture
def backend_setup(monkeypatch):
    state.close_backend()
    events = []
    backends = []
    def factory(cfg):
        backend = COMBackend(cfg, session_factory=lambda cfg: RecordingSession(cfg, events))
        backends.append(backend)
        return backend
    monkeypatch.setattr(state, "load_config", config)
    monkeypatch.setattr(state, "create_backend", factory)
    yield events, backends
    state.close_backend()


@pytest.mark.parametrize("first", ["query", "controller"])
def test_access_order_uses_one_lazy_session(first, backend_setup):
    events, backends = backend_setup
    getters = [state.get_query, state.get_controller]
    if first == "controller":
        getters.reverse()
    for getter in getters:
        getter()
    assert len(backends) == 1
    assert events == []  # Accessors and tool discovery cannot start CAD.
    assert state.get_query().list_layers() == ["scratch-1"]
    assert state.get_controller().draw_line((0, 0, 0), (1, 0, 0)) == 101
    assert [name for name, _ in events].count("connect") == 1


def test_new_document_shared_with_existing_facades(backend_setup):
    query, controller = state.get_query(), state.get_controller()
    assert query.query_entities() == [{"document": "scratch-1"}]
    assert state.new_document() == "scratch-2"
    assert query.query_entities() == [{"document": "scratch-2"}]
    assert controller.draw_line((0, 0, 0), (1, 0, 0)) == 101


def test_close_and_explicit_reconnect(backend_setup):
    events, backends = backend_setup
    old_query = state.get_query()
    old_query.list_layers()
    state.close_backend()
    state.close_backend()
    with pytest.raises(BackendClosedError):
        old_query.list_layers()
    state.get_query().list_layers()
    assert len(backends) == 2
    assert [name for name, _ in events].count("close") == 1


def test_all_calls_and_release_share_one_sta_thread(backend_setup, monkeypatch):
    import pythoncom
    events, _ = backend_setup
    original_init, original_uninit = pythoncom.CoInitializeEx, pythoncom.CoUninitialize
    def initialize(flags):
        assert flags == pythoncom.COINIT_APARTMENTTHREADED
        events.append(("initialize", get_ident()))
        original_init(flags)
    def uninitialize():
        events.append(("uninitialize", get_ident()))
        original_uninit()
    monkeypatch.setattr(pythoncom, "CoInitializeEx", initialize)
    monkeypatch.setattr(pythoncom, "CoUninitialize", uninitialize)
    with ThreadPoolExecutor(max_workers=8) as callers:
        results = list(callers.map(lambda _: state.get_query().list_layers(), range(32)))
    state.close_backend()
    assert results == [["scratch-1"]] * 32
    assert len({thread_id for _, thread_id in events}) == 1
    assert events[0][0] == "initialize"
    assert [name for name, _ in events][-2:] == ["close", "uninitialize"]
    assert events[0][1] != get_ident()


def test_failed_connection_not_cached_or_replayed():
    events = []
    def create(cfg):
        events.append("connect")
        if len(events) == 1:
            raise RuntimeError("connection failed before execution")
        return RecordingSession(cfg, [])
    backend = COMBackend(config(), session_factory=create)
    try:
        with pytest.raises(RuntimeError, match="connection failed"):
            backend.execute("list_layers", {})
        assert events == ["connect"]
        assert backend.execute("list_layers", {}) == ["scratch-1"]
    finally:
        backend.close()


def test_write_failure_is_never_replayed_and_worker_survives():
    operations = []
    class Session(RecordingSession):
        def execute(self, operation, payload):
            operations.append(operation)
            if operation == "draw_line":
                raise RuntimeError("result unknown after write")
            return []
    backend = COMBackend(config(), session_factory=lambda cfg: Session(cfg, []))
    try:
        with pytest.raises(RuntimeError, match="result unknown"):
            backend.execute("draw_line", {"start": (0, 0, 0), "end": (1, 0, 0)})
        assert backend.execute("list_layers", {}) == []
        assert operations == ["draw_line", "list_layers"]
    finally:
        backend.close()


def test_closed_backend_and_invalid_operations_do_not_connect():
    events = []
    backend = COMBackend(config(), session_factory=lambda cfg: RecordingSession(cfg, events))
    with pytest.raises(UnsupportedOperationError):
        backend.execute("__getattribute__", {})
    with pytest.raises(TypeError):
        backend.execute("draw_line", {"start": (0, 0, 0)})
    facade = OperationFacade(backend, CONTROLLER_OPERATIONS)
    with pytest.raises(AttributeError):
        _ = facade.connection
    with pytest.raises(TypeError, match="plain data"):
        backend.execute("draw_line", {"start": object(), "end": (1, 0, 0)})
    assert backend.capabilities()["atomic_batch"] is False
    backend.close()
    with pytest.raises(BackendClosedError):
        backend.execute("list_layers", {})
    assert events == []


def test_queue_limit_and_close_drain_without_data_races():
    started, release, queued, closing = Event(), Event(), Event(), Event()
    received = []
    class Session:
        def execute(self, operation, payload):
            if not started.is_set():
                started.set()
                assert release.wait(5)
            received.append(payload)
            return []
        def close(self):
            received.append("closed")
    backend = COMBackend(config(), session_factory=lambda _: Session(), queue_size=1)
    original_put = backend._queue.put_nowait
    def put(item):
        original_put(item)
        if started.is_set():
            queued.set()
    backend._queue.put_nowait = put
    payload = {"updates": [{"object_id": 1, "tag": "ID", "value": "original"}]}
    with ThreadPoolExecutor(max_workers=3) as callers:
        first = callers.submit(backend.execute, "list_layers", {})
        try:
            assert started.wait(5)
            second = callers.submit(backend.execute, "bulk_set_block_attributes", payload)
            assert queued.wait(5)
            payload["updates"][0]["value"] = "mutated"
            with pytest.raises(BackendQueueFullError):
                backend.execute("list_layers", {})
            def close():
                closing.set()
                backend.close()
            closed = callers.submit(close)
            assert closing.wait(5)
        finally:
            release.set()
        first.result(timeout=5)
        second.result(timeout=5)
        closed.result(timeout=5)
    assert received == [{}, {"updates": [{"object_id": 1, "tag": "ID", "value": "original"}]}, "closed"]
    with pytest.raises(BackendClosedError):
        backend.execute("list_layers", {})


def test_config_backwards_compatibility_and_no_http_fallback():
    assert config().backend == "com"
    backend = create_backend(config())
    backend.close()
    with pytest.raises(UnsupportedBackendError, match="not implemented"):
        create_backend(config(backend="http"))
    with pytest.raises(ValidationError):
        config(backend="typo")


def test_document_switch_is_rejected_and_disconnect_has_no_side_effects():
    conn = CADConnection(config())
    original = SimpleNamespace(Name="scratch-1")
    conn.document = original
    conn.model_space = object()
    conn.app = SimpleNamespace(ActiveDocument=original)
    conn.ensure_document()
    conn.app.ActiveDocument = SimpleNamespace(Name="user-project")
    with pytest.raises(CADDocumentChangedError):
        conn.ensure_document()
    assert conn.document is original
    conn.disconnect()
    assert conn.app is conn.document is conn.model_space is None


def test_com_session_guards_before_writes_and_refreshes_new_document(monkeypatch):
    from autocad_mcp.cad import connection
    instances = []
    class Connection:
        def __init__(self, cfg):
            self.config = cfg
            self.document = SimpleNamespace(Name="scratch-1")
            self.switched = False
            instances.append(self)
        def connect(self): pass
        def ensure_document(self):
            if self.switched:
                raise CADDocumentChangedError("changed")
        def new_document(self):
            self.document = SimpleNamespace(Name="scratch-2")
            self.switched = False
        def disconnect(self): self.document = None
    monkeypatch.setattr(connection, "CADConnection", Connection)
    session = COMSession(config())
    instances[0].switched = True
    with pytest.raises(CADDocumentChangedError):
        session.execute("draw_line", {"start": (0, 0, 0), "end": (1, 0, 0)})
    assert session.execute("new_document", {}) == "scratch-2"
    session.close()
    assert instances[0].document is None


def test_unexpected_worker_failure_fails_waiters(monkeypatch):
    import pythoncom
    failed = Event()
    def pump():
        failed.set()
        raise RuntimeError("injected message pump failure")
    monkeypatch.setattr(pythoncom, "PumpWaitingMessages", pump)
    backend = COMBackend(config(), session_factory=lambda cfg: RecordingSession(cfg, []))
    try:
        assert backend.execute("list_layers", {}) == ["scratch-1"]
        assert failed.wait(5)
        with pytest.raises(BackendWorkerError):
            backend.execute("list_layers", {})
    finally:
        backend.close()


@pytest.mark.parametrize("size", [0, -1])
def test_queue_must_be_bounded(size):
    with pytest.raises(ValueError, match="positive"):
        COMBackend(config(), queue_size=size)


def test_reference_restore_failure_cannot_rebind_future_writes(monkeypatch):
    from autocad_mcp.cad import reference_library
    from autocad_mcp.cad.connection import CADConnectionError
    conn = CADConnection(config())
    conn.document = SimpleNamespace(Name="scratch")
    conn.model_space = object()
    conn.app = SimpleNamespace(ActiveDocument=conn.document)
    def analyze(connection, **kwargs):
        connection.document = SimpleNamespace(Name="unexpected-user-document")
        connection.app.ActiveDocument = connection.document
        return {}
    monkeypatch.setattr(reference_library, "analyze_reference_drawing", analyze)
    session = COMSession.__new__(COMSession)
    session.connection = conn
    with pytest.raises(CADDocumentChangedError, match="did not restore"):
        session.execute("analyze_reference_drawing", {"file_path":"reference.dwg"})
    assert conn.document is None and conn.model_space is None
    with pytest.raises(CADConnectionError):
        conn.ensure_document()


def test_failed_document_refresh_preserves_consistent_snapshot(monkeypatch):
    from autocad_mcp.cad import connection
    from autocad_mcp.cad.connection import CADConnectionError
    conn = CADConnection(config())
    original_doc, original_space = object(), object()
    conn.document, conn.model_space = original_doc, original_space
    class NotReady:
        @property
        def ModelSpace(self):
            raise AttributeError("not ready")
    conn.app = SimpleNamespace(ActiveDocument=NotReady())
    clock = iter([0, 0, 2])
    monkeypatch.setattr(connection.time, "time", lambda: next(clock))
    monkeypatch.setattr(connection.time, "sleep", lambda _: None)
    with pytest.raises(CADConnectionError, match="超时"):
        conn._wait_for_document(1)
    assert conn.document is original_doc
    assert conn.model_space is original_space
