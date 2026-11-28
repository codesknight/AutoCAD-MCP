"""One lazy, serial STA worker owns every native object of this backend.

Accepted operations drain on close. No operation is automatically retried;
closing drops references without saving drawings or quitting AutoCAD.
"""
import logging
from concurrent.futures import Future
from inspect import Parameter
from queue import Empty, Full, Queue
from threading import Lock, Thread
from typing import Callable
from uuid import uuid4

from pydantic import TypeAdapter

from autocad_mcp.cad.backends.base import (
    CONTROLLER_OPERATIONS,
    OPERATIONS,
    QUERY_OPERATIONS,
    copy_data,
    operation_signature,
)
from autocad_mcp.cad.com_artifacts import OPERATIONS as FILE_OPERATIONS
from autocad_mcp.cad.com_artifacts import COMArtifacts
from autocad_mcp.cad.errors import (
    BackendClosedError,
    BackendQueueFullError,
    BackendWorkerError,
    UnsupportedOperationError,
)
from autocad_mcp.cad.execution import (
    READS,
    SUPPORTED,
    ExecutionJournal,
    ExecutionTrace,
    error_details,
    support_matrix,
)
from autocad_mcp.config import Config


class COMSession:
    """Construct, use, and dispose on the owning STA thread only."""
    def __init__(self, config: Config, *, attach_only=False):
        from autocad_mcp.cad.connection import CADConnection
        from autocad_mcp.cad.controller import CADController
        from autocad_mcp.cad.query import CADQuery
        self.connection = CADConnection(config)
        try:
            if attach_only:
                self.connection.connect(allow_launch=False)
            else:
                self.connection.connect()
        except Exception:
            self.connection.disconnect()
            raise
        self.controller = CADController(self.connection)
        self.query = CADQuery(self.connection)
        self.files = COMArtifacts(self.connection)

    def execute(self, operation: str, payload: dict):
        if operation == "new_document":
            self.connection.new_document()
            from autocad_mcp.cad.capture import prop
            return prop(self.connection.document, "Name")
        self.connection.ensure_document()
        if operation in CONTROLLER_OPERATIONS:
            return getattr(self.controller, operation)(**payload)
        if operation in QUERY_OPERATIONS:
            return getattr(self.query, operation)(**payload)
        from autocad_mcp.cad.connection import CADDocumentChangedError
        from autocad_mcp.cad.reference_library import analyze_reference_drawing
        expected_id = self.connection.document_id(self.connection.document)
        try:
            return analyze_reference_drawing(self.connection, **payload)
        finally:
            try:
                if self.connection.document_id(self.connection.document) != expected_id:
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
        self.instance_id = uuid4().hex
        self.journal = ExecutionJournal(self.instance_id)
        self._last_binding = None

    def capabilities(self) -> dict:
        return {"backend": "com", "operations": sorted(OPERATIONS),
                "atomic_batch": False, "query_pagination":False,"execution": "serial_sta",
                "evidence_support": support_matrix("com")}

    def runtime_status(self) -> dict:
        # Lifecycle metadata only: status/discovery never launches CAD or probes a native object.
        with self._lock:
            phase="closed" if self._closed else "worker_failed" if self._failure else "not_started" if self._thread is None else "worker_running"
            return {"backend":"com","state":phase,"connection_state":"not_probed",
                    "queue_depth":self._queue.qsize(),"capabilities":self.capabilities(),
                    "instance_id":self.instance_id,"revision_mode":"unsupported",
                    "bound_document_id":self._last_binding["document_id"] if self._last_binding else None,
                    "documents":[{**self._last_binding,"observation":"cached_not_live"}] if self._last_binding else []}

    def document_binding(self):
        return self.execute("_document_binding", {})

    def execution_status(self, instance_id, request_id):
        return self.journal.lookup(instance_id, request_id)

    def execute_evidenced(self, operation, args, *, request_id, instance_id, document_id=None):
        args = copy_data(args)
        added = self.journal.accept(request_id, operation, args, instance_id, document_id)
        if not added:
            return dict(receipt=self.execution_status(self.instance_id, request_id), result=None)
        try:
            if instance_id != self.instance_id:
                raise ValueError("INSTANCE_MISMATCH")
            if operation not in SUPPORTED:
                raise UnsupportedOperationError("Operation has no declared COM execution receipt")
            if (operation in {"new_document", "fork_checkpoint"}) != (document_id is None):
                raise ValueError("DOCUMENT_ID_REQUIRED: new_document/fork_checkpoint require null input document")
            from inspect import signature as inspect_signature
            signature = (inspect_signature(getattr(COMArtifacts,operation)).replace(
                parameters=list(inspect_signature(getattr(COMArtifacts,operation)).parameters.values())[1:])
                if operation in FILE_OPERATIONS else operation_signature(operation))
            bound = signature.bind(**args)
            values = {name:(TypeAdapter(signature.parameters[name].annotation).validate_python(value)
                      if signature.parameters[name].annotation is not Parameter.empty else value)
                      for name,value in bound.arguments.items()}
            # Conversion must not introduce a nonfinite value from e.g. "NaN".
            import json
            json.dumps(values,allow_nan=False)
            data = dict(operation=operation, args=copy_data(values), request_id=request_id, document_id=document_id)
            return self.execute("_execute_receipt", data)
        except Exception as error:
            # Admission/session failures occur before a traced native action.
            record = self.execution_status(self.instance_id, request_id)
            if record.get("status") == "pending":
                stage = "result_unknown" if record["native_invoked"] else "not_dispatched"
                self.journal.update(request_id, status="failed", stage=stage,
                                    error=error_details(error))
            return dict(receipt=self.execution_status(self.instance_id, request_id), result=None)

    def _execute_receipt(self, session, data):
        request_id, operation, args = data["request_id"], data["operation"], data["args"]
        connection = session.connection
        if operation == "fork_checkpoint":
            previous_binding = (connection.document, connection.model_space)
            previous_owned = set(connection._owned_ids)
        self.journal.update(request_id, stage="preflight")
        try:
            with ExecutionTrace(self.journal, request_id):
                if not hasattr(session,"files"):
                    session.files=COMArtifacts(connection)
                if operation in FILE_OPERATIONS:
                    session.files.progress=None
                    session.files.request_id=request_id
                if operation not in {"new_document","query_verification_entities", "fork_checkpoint"}:
                    binding = connection.binding()
                    if binding["document_id"] != data["document_id"]:
                        raise ValueError("DOCUMENT_ID_MISMATCH")
                    if operation not in READS and binding["read_only"]:
                        raise ValueError("READ_ONLY_DOCUMENT")
                    if operation not in READS and not binding["managed"]:
                        raise ValueError("UNMANAGED_DOCUMENT: create a new working document in this session")
                if operation in READS:
                    self.journal.update(request_id, stage="observing", observation="pending")
                if operation == "query_verification_entities" and args["document_id"]!=data["document_id"]:
                    raise ValueError("VERIFICATION_DOCUMENT_ID_MISMATCH")
                if operation in FILE_OPERATIONS:
                    session.files.progress=None
                    result=copy_data(getattr(session.files,operation)(**args))
                    self.journal.update(request_id,file_result=result,file_progress=session.files.progress)
                else:
                    result = copy_data(session.execute(operation, args))
                affected = dict(created=[],modified=[],deleted=[],complete=True)
                if operation in {"draw_line","draw_circle","draw_text","draw_polyline"}:
                    affected["created"] = [str(result)]
                if operation in {"move_entity","delete_entity"}:
                    affected["deleted" if operation=="delete_entity" else "modified"] = [str(args["object_id"])]
                self.journal.update(request_id, observation="pending", affected_entities=affected)
                if operation == "query_verification_entities":
                    binding={"document_id":args["document_id"]}
                else:
                    binding = connection.binding()
                    with self._lock:
                        self._last_binding = copy_data(binding)
                result_document=(result["document_id"] if operation=="reopen_document_artifact" else binding["document_id"])
                self.journal.update(request_id, status="succeeded",stage="completed",observation="succeeded",
                                    result_document_id=result_document,affected_entities=affected)
                return dict(receipt=self.execution_status(self.instance_id, request_id), result=result)
        except Exception as error:
            if operation == "fork_checkpoint":
                # A failed verification/postflight never leaves a writable binding.
                connection._owned_ids.intersection_update(previous_owned)
                connection.document, connection.model_space = previous_binding
            record = self.execution_status(self.instance_id, request_id)
            if operation == "fork_checkpoint" and record.get("file_result"):
                self.journal.update(request_id, file_result={**record["file_result"],
                    "managed":False, "binding_valid":False})
            stage = ("result_unknown" if record["native_invoked"] and not record["native_acknowledged"] else
                     "observation_failed" if record["native_acknowledged"] or record["observation"]=="pending" else "not_dispatched")
            self.journal.update(request_id,status="failed",stage=stage,observation="failed",
                                affected_entities={**record["affected_entities"],"complete":False},
                                error=error_details(error),
                                native_detail=getattr(error,"evidence",None))
            if operation in FILE_OPERATIONS:
                self.journal.update(request_id,file_progress=getattr(session.files,"progress",None))
            return dict(receipt=self.execution_status(self.instance_id, request_id),result=None)

    def execute(self, operation: str, payload: dict):
        # Reject unknown operations and invalid payloads before any CAD startup.
        if operation not in {"_document_binding", "_execute_receipt"}:
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
                        if self._session_factory is COMSession and operation in {"_document_binding","_execute_receipt"}:
                            session = COMSession(self._config, attach_only=True)
                        else:
                            session = self._session_factory(self._config)
                        if hasattr(session, "connection"):
                            session.connection.instance_id = self.instance_id
                    if operation == "_document_binding":
                        result = session.connection.binding()
                        with self._lock:
                            self._last_binding = copy_data(result)
                    elif operation == "_execute_receipt":
                        result = self._execute_receipt(session, payload)
                    else:
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
