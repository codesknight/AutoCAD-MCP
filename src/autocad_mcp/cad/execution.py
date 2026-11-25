"""Service-local execution facts. No native object, retry, or database revision."""
import hashlib
import json
import re
import time
from contextvars import ContextVar
from copy import deepcopy
from threading import RLock

VERSION = "autocad-execution/1"
SUPPORTED = frozenset({"new_document", "draw_line", "draw_circle", "draw_text",
                       "move_entity", "delete_entity", "save_drawing",
                       "get_entity", "query_entities", "export_current_view",
                       "save_document_artifact","reopen_document_artifact","query_verification_entities"})
READS = frozenset({"get_entity", "query_entities","query_verification_entities"})
_trace = ContextVar("cad_execution_trace", default=None)


def observing_execution():
    return _trace.get() is not None


def error_details(error):
    result=dict(type=type(error).__name__,message=str(error),hresult=getattr(error,"hresult",None))
    causes=[];seen={id(error)};cause=error.__cause__
    while cause is not None and id(cause) not in seen and len(causes)<8:
        seen.add(id(cause))
        causes.append(dict(type=type(cause).__name__,message=str(cause),hresult=getattr(cause,"hresult",None)))
        cause=cause.__cause__
    result["causes"]=causes
    return result


def native_action(name, action):
    """Call a mutator once. ACK means return from this exact native call only."""
    trace = _trace.get()
    if trace is None:
        return action()
    trace.action(name, False)
    value = action()
    trace.action(name, True)
    return value


def invoke_mutator(obj, name, *args):
    from autocad_mcp.cad.capture import method
    action = method(obj, name)
    return native_action(name, lambda: action(*args))


def set_property(obj, name, value):
    import pythoncom
    ole = getattr(obj, "_oleobj_", None)
    if ole is not None:
        dispid = ole.GetIDsOfNames(name)
        return native_action("set_"+name, lambda: ole.Invoke(
            dispid, 0, pythoncom.DISPATCH_PROPERTYPUT, False, value))
    return native_action("set_"+name, lambda: setattr(obj, name, value))


class ExecutionJournal:
    def __init__(self, instance_id, capacity=2048, ttl=600, clock=time.monotonic):
        self.instance_id = instance_id
        self.capacity, self.ttl, self.clock = capacity, ttl, clock
        self.lock = RLock()
        self.records = {}

    def _expire(self):
        now = self.clock()
        for key, (_, _, finished) in list(self.records.items()):
            if finished is not None and now-finished >= self.ttl:
                del self.records[key]

    def accept(self, request_id, operation, args, instance_id, document_id):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", request_id):
            raise ValueError("INVALID_REQUEST_ID")
        raw = json.dumps([operation, args, instance_id, document_id], sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        with self.lock:
            self._expire()
            if request_id in self.records:
                if self.records[request_id][0] != digest:
                    raise ValueError("REQUEST_ID_CONFLICT: original record retained")
                return False
            if len(self.records) >= self.capacity:
                raise ValueError("EXECUTION_JOURNAL_FULL: no request dispatched")
            receipt = dict(contract=VERSION, backend="com", instance_id=self.instance_id,
                request_id=request_id, operation=operation, request_document_id=document_id,
                request_instance_id=instance_id,
                result_document_id=None, status="pending", stage="queued", revision=None,
                revision_mode="unsupported", native_actions=[], native_invoked=False,
                native_acknowledged=False, observation="not_started", error=None,
                affected_entities=dict(created=[], modified=[], deleted=[], complete=False),
                retention=dict(scope="python_backend_lifetime", terminal_ttl_seconds=self.ttl,
                               capacity=self.capacity), service_request_fingerprint=digest,
                fingerprint_algorithm="sha256-canonical-com-request-v1")
            self.records[request_id] = (digest, receipt, None)
            return True

    def update(self, request_id, **fields):
        with self.lock:
            digest, record, finished = self.records[request_id]
            record.update(deepcopy(fields))
            if record["status"] != "pending" and finished is None:
                finished = self.clock()
            self.records[request_id] = digest, record, finished

    def action(self, request_id, name, acknowledged):
        with self.lock:
            record = self.records[request_id][1]
            if not acknowledged:
                record["native_actions"].append(dict(name=name, acknowledged=False))
            else:
                record["native_actions"][-1]["acknowledged"] = True
            record["native_invoked"] = True
            record["native_acknowledged"] = all(x["acknowledged"] for x in record["native_actions"])
            record["stage"] = "native_acknowledged" if record["native_acknowledged"] else "dispatching"

    def lookup(self, instance_id, request_id):
        with self.lock:
            if instance_id != self.instance_id:
                return dict(contract=VERSION, backend="com", instance_id=self.instance_id,
                            request_id=request_id, status="unresolved", reason="INSTANCE_MISMATCH",
                            replay_safe=False)
            self._expire()
            if request_id not in self.records:
                return dict(contract=VERSION, backend="com", instance_id=self.instance_id,
                            request_id=request_id, status="unresolved", reason="RECORD_NOT_AVAILABLE",
                            replay_safe=False)
            return deepcopy(self.records[request_id][1])


class ExecutionTrace:
    def __init__(self, journal, request_id):
        self.journal, self.request_id = journal, request_id

    def action(self, name, acknowledged):
        self.journal.action(self.request_id, name, acknowledged)

    def __enter__(self):
        self.token = _trace.set(self)
        return self

    def __exit__(self, *unused):
        _trace.reset(self.token)


def support_matrix(backend, native=None):
    native = native or {}
    http = backend == "http"
    revision = http and native.get("revision_mode") == "observed_database_events"
    return dict(contract="autocad-backend-evidence/1",
        document_identity=dict(supported=True, scope="bridge_instance" if http else "python_com_session",
                               mechanism="native_document_lifecycle" if http else "canonical_iunknown_lifecycle",
                               python_reconnect_reuses_ids=http, cad_restart_reuses_ids=False,
                               entity_ids_scope="document"),
        revision=dict(authoritative=revision, manual_edits_observed=revision,
                      mode="observed_database_events" if revision else "unsupported", value=None),
        execution_receipts=dict(supported=True, contract=VERSION if not http else "bridge-job/1",
                                operations=sorted(SUPPORTED) if not http else native.get("operations", []),
                                native_action_ack=not http, automatic_write_replay=False,
                                entrypoint="execute_observed_operation" if not http else "existing_bridge_tools"),
        reconciliation=dict(supported=True, scope="bridge_instance" if http else "python_backend_lifetime",
                            survives_python_restart=http, survives_cad_restart=False,
                            terminal_ttl_seconds=native.get("job_ttl_seconds", 600) if http else 600,
                            capacity=2048, missing_record_proves_not_executed=False),
        readonly_reopen=dict(supported=(bool(native.get("controlled_documents")) and
                             "reopen_artifact" in native.get("operations",[])) if http else True,
                             scope="instance_owned_artifacts" if http else "python_backend_owned_artifacts"),
        file_artifacts=dict(contract="autocad-file-artifact/1" if not http else None,
                            persistent=False,source_revision_authoritative=revision,
                            save_semantics="copy_save" if http else "save_as_renames_source",
                            output_namespace="unique_artifact_subdirectory" if not http else "bound_directory",
                            overwrite=False,atomic_with_entities=False),
        capture=dict(receipt_contract="autocad-capture/1" if not http else None,
                     state_restoration=not http, pixel_to_cad="unavailable"),
        batch=dict(atomic=bool(native.get("atomic_batch")) if http else False,
                   operations=native.get("batch_operations", []) if http else [],
                   file_operations_atomic=False),
        query=dict(pagination=bool(native.get("query_pagination")) if http else False,
                   fields_projection=bool(native.get("query_pagination")) if http else False,
                   revision_bound=revision and bool(native.get("query_pagination")), since_revision=False))
