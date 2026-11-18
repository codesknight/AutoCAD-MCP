"""One lazy, serial STA worker owns every native object of this backend.

Accepted operations drain on close. No operation is automatically retried;
closing drops references without saving drawings or quitting AutoCAD.
"""
import logging

from concurrent.futures import Future
from queue import Empty, Full, Queue
from threading import Lock, Thread
from typing import Callable

from autocad_mcp.config import Config
from autocad_mcp.cad.errors import BackendClosedError, BackendQueueFullError, BackendWorkerError
from autocad_mcp.cad.backends.base import (
    CONTROLLER_OPERATIONS, QUERY_OPERATIONS, OPERATIONS,
    copy_data, operation_signature,
)

class COMSession:
    """Construct, use, and dispose on the owning STA thread only."""
    def __init__(self, config: Config):
        from autocad_mcp.cad.connection import CADConnection
        from autocad_mcp.cad.controller import CADController
        from autocad_mcp.cad.query import CADQuery
        self.connection = CADConnection(config)
        try:
            self.connection.connect()
        except Exception:
            self.connection.disconnect()
            raise
        self.controller = CADController(self.connection)
        self.query = CADQuery(self.connection)

    def execute(self, operation: str, payload: dict):
        if operation == "new_document":
            self.connection.new_document()
            return self.connection.document.Name
        self.connection.ensure_document()
        if operation in CONTROLLER_OPERATIONS:
            return getattr(self.controller, operation)(**payload)
        if operation in QUERY_OPERATIONS:
            return getattr(self.query, operation)(**payload)
        from autocad_mcp.cad.reference_library import analyze_reference_drawing
        from autocad_mcp.cad.connection import CADDocumentChangedError
        expected_name = self.connection.document.Name
        try:
            return analyze_reference_drawing(self.connection, **payload)
        finally:
            try:
                if self.connection.document.Name != expected_name:
                    raise CADDocumentChangedError("Reference analysis did not restore the bound document")
            except Exception:
                # The legacy helper refreshes references after switching documents.
                # A failed restore must invalidate the session, never rebind writes.
                self.connection.document = None
                self.connection.model_space = None
                raise

    def close(self):
        self.controller = None
        self.query = None
        self.connection.disconnect()
        self.connection = None

class COMBackend:
    def __init__(self, config: Config, *, session_factory: Callable = COMSession,
                 queue_size: int = 64):
        if queue_size < 1:
            raise ValueError("queue_size must be positive")
        self._config = config.model_copy(deep=True)
        self._session_factory = session_factory
        self._queue: Queue = Queue(maxsize=queue_size)
        self._lock = Lock()
        self._thread: Thread | None = None
        self._closed = False
        self._failure: BackendWorkerError | None = None

    def capabilities(self) -> dict:
        return {"backend": "com", "operations": sorted(OPERATIONS),
                "atomic_batch": False, "execution": "serial_sta"}

    def execute(self, operation: str, payload: dict):
        # Reject unknown operations and invalid payloads before any CAD startup.
        operation_signature(operation).bind(**payload)
        data = copy_data(payload)
        future = Future()
        with self._lock:
            if self._closed:
                raise BackendClosedError("CAD backend is closed; obtain a new session")
            if self._failure is not None:
                raise self._failure
            if self._thread is None:
                self._thread = Thread(target=self._run, name="autocad-com-sta", daemon=True)
                self._thread.start()
            try:
                self._queue.put_nowait((operation, data, future))
            except Full:
                raise BackendQueueFullError("CAD execution queue is full") from None
        # Deliberately no timeout/replay: a timed-out write can still complete.
        return future.result()

    def _run(self):
        session = None
        initialized = False
        current = None
        try:
            import pythoncom
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            initialized = True
            while True:
                try:
                    operation, payload, current = self._queue.get(timeout=0.05)
                except Empty:
                    with self._lock:
                        if self._closed:
                            break
                    pythoncom.PumpWaitingMessages()
                    continue
                try:
                    if session is None:
                        session = self._session_factory(self._config)
                    result = copy_data(session.execute(operation, payload))
                except Exception as exc:
                    current.set_exception(exc)
                else:
                    current.set_result(result)
                current = None
                pythoncom.PumpWaitingMessages()
        except BaseException:
            # A dead worker must fail waiters, never leave Future.result hanging.
            logging.getLogger(__name__).exception("CAD STA worker stopped")
            error = BackendWorkerError("CAD STA worker stopped; close/recreate the backend")
            with self._lock:
                self._failure = error
                if current is not None and not current.done():
                    current.set_exception(error)
                while True:
                    try:
                        _, _, pending = self._queue.get_nowait()
                    except Empty:
                        break
                    pending.set_exception(error)
        finally:
            try:
                if session is not None:
                    session.close()
                    session = None
            finally:
                if initialized:
                    pythoncom.CoUninitialize()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            thread = self._thread
        # The worker drains admitted tasks and exits when its queue is empty.
        # No sentinel insertion into a full queue while holding the state lock.
        if thread is not None:
            thread.join()
