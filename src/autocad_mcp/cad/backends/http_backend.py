"""Authenticated loopback Bridge client. Never retries/replays a write request."""
import os
import re
import time
from threading import RLock
from uuid import uuid4

import httpx
from pydantic import ValidationError

from autocad_mcp.cad.backends.base import copy_data, operation_signature
from autocad_mcp.cad.errors import (
    BackendClosedError,
    BackendError,
    UnsupportedOperationError,
)
from autocad_mcp.cad.models import BridgeJob, SavedArtifactJob, WorkingDocumentJob
from autocad_mcp.config import Config


class BridgeRemoteError(BackendError):
    def __init__(self, code, message, *, request_id=None, outcome="not_executed"):
        self.code, self.request_id, self.outcome = code, request_id, outcome
        suffix = f"; request_id={request_id}" if request_id else ""
        super().__init__(f"{code}: {message}{suffix}; outcome={outcome}")

class HTTPBackend:
    def __init__(self, config: Config, *, client: httpx.Client | None = None):
        self._config = config.http.model_copy(deep=True)
        self._client = client or httpx.Client(
            base_url=self._config.base_url, trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(self._config.request_timeout_seconds, connect=self._config.connect_timeout_seconds),
        )
        self._lock = RLock()
        self._instance = None
        self._capabilities = None
        self._document = None
        self._closed = False

    def _request(self, method, path, *, payload=None, request_id=None, timeout=None):
        if self._closed:
            raise BackendClosedError("CAD HTTP backend is closed")
        token = os.environ.get(self._config.token_env, "")
        if len(token) < 32:
            raise BridgeRemoteError("UNAUTHORIZED", "Bridge token environment variable must contain at least 32 characters")
        try:
            options = {"timeout": timeout} if timeout is not None else {}
            response = self._client.request(method, path, json=payload,
                headers={"Authorization": f"Bearer {token}"}, **options)
        except httpx.RequestError:
            code = "OUTCOME_UNKNOWN" if method == "POST" else "CONNECTION_LOST"
            raise BridgeRemoteError(code, "Bridge request failed; inspect the job before any further write",
                request_id=request_id, outcome="outcome_unknown" if method == "POST" else "not_executed") from None
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
        except ValueError:
            raise BridgeRemoteError("OUTCOME_UNKNOWN" if method == "POST" else "PROTOCOL_ERROR",
                "Bridge returned an invalid response", request_id=request_id,
                outcome="outcome_unknown" if method == "POST" else "not_executed") from None
        if response.status_code not in {200, 202}:
            error = data.get("error") or {}
            outcome = "outcome_unknown" if path.startswith("/v1/jobs/") else error.get("outcome", "not_executed")
            raise BridgeRemoteError(error.get("code", "PROTOCOL_ERROR"), error.get("message", "Bridge rejected request"),
                request_id=request_id, outcome=outcome)
        if self._instance is not None and data.get("instance_id") != self._instance:
            raise BridgeRemoteError("OUTCOME_UNKNOWN", "Bridge instance changed; reconnect explicitly and re-read the drawing",
                request_id=request_id, outcome="outcome_unknown")
        return data

    def _connect(self):
        if self._capabilities is not None:
            return
        health = self._request("GET", "/v1/health")
        if health.get("protocol_version") != "1" or not isinstance(health.get("instance_id"), str) or not health["instance_id"]:
            raise BridgeRemoteError("PROTOCOL_ERROR", "Unsupported Bridge protocol or missing instance identity")
        if health.get("status") != "ready":
            raise BridgeRemoteError("CAD_BUSY", "Bridge is stopping or its dispatcher is unavailable")
        self._instance = health["instance_id"]
        capabilities = self._request("GET", "/v1/capabilities")
        if capabilities.get("protocol_version") != "1" or not isinstance(capabilities.get("operations"), list) or any(not isinstance(op, str) for op in capabilities["operations"]):
            raise BridgeRemoteError("PROTOCOL_ERROR", "Invalid Bridge capabilities")
        status = self._status()
        self._document = status.get("active_document_id")
        self._capabilities = capabilities

    def _status(self):
        try:
            job = BridgeJob.model_validate(self._request("GET", "/v1/status"))
        except ValidationError:
            raise BridgeRemoteError("PROTOCOL_ERROR", "Invalid CAD status envelope") from None
        if job.status != "succeeded" or not isinstance(job.result, dict):
            raise BridgeRemoteError("CAD_BUSY", "CAD status is not available")
        return job.result

    def status(self):
        with self._lock:
            self._connect()
            return self._status()

    def capabilities(self):
        with self._lock:
            self._connect()
            return copy_data(self._capabilities)

    def _submit(self, path, payload, *, allow_failure=False):
        request_id = payload["request_id"]
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", request_id):
            raise ValueError("Invalid Bridge request ID")
        payload = {**payload, "instance_id": self._instance}
        data = self._request("POST", path, payload=payload, request_id=request_id)
        deadline = time.monotonic() + self._config.request_timeout_seconds
        while True:
            try:
                job = BridgeJob.model_validate(data)
            except ValidationError:
                raise BridgeRemoteError("OUTCOME_UNKNOWN", "Invalid job result; inspect drawing before writing again",
                    request_id=request_id, outcome="outcome_unknown") from None
            if job.request_id != request_id:
                raise BridgeRemoteError("OUTCOME_UNKNOWN", "Job identity mismatch", request_id=request_id, outcome="outcome_unknown")
            if job.status not in {"queued", "running"}:
                if job.status != "succeeded" and not allow_failure:
                    error = job.error
                    raise BridgeRemoteError(error.code, error.message, request_id=request_id, outcome=error.outcome)
                if payload.get("document_id") is not None and job.document_id != payload["document_id"]:
                    raise BridgeRemoteError("OUTCOME_UNKNOWN", "Document identity mismatch", request_id=request_id, outcome="outcome_unknown")
                return job
            if time.monotonic() >= deadline:
                raise BridgeRemoteError("OUTCOME_UNKNOWN", "CAD job is still pending; query its status without resending",
                    request_id=request_id, outcome="outcome_unknown")
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BridgeRemoteError("OUTCOME_UNKNOWN", "CAD job did not finish within the wait budget",
                    request_id=request_id, outcome="outcome_unknown")
            try:
                data = self._request("GET", f"/v1/jobs/{request_id}", request_id=request_id,
                    timeout=min(remaining, self._config.request_timeout_seconds))
            except BridgeRemoteError:
                raise BridgeRemoteError("OUTCOME_UNKNOWN", "Cannot confirm the accepted job; query it before writing again",
                    request_id=request_id, outcome="outcome_unknown") from None

    def get_job(self, request_id):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", request_id):
            raise ValueError("Invalid Bridge request ID")
        with self._lock:
            self._connect()
            try:
                job=BridgeJob.model_validate(self._request("GET", f"/v1/jobs/{request_id}", request_id=request_id))
            except ValidationError:
                raise BridgeRemoteError("PROTOCOL_ERROR","Invalid job status envelope",request_id=request_id,outcome="outcome_unknown") from None
            if job.request_id!=request_id:
                raise BridgeRemoteError("PROTOCOL_ERROR","Job identity mismatch",request_id=request_id,outcome="outcome_unknown")
            return job

    def execute(self, operation, payload, *, request_id=None, expected_revision=None):
        operation_signature(operation).bind(**payload)
        with self._lock:
            self._connect()
            if operation not in self._capabilities["operations"]:
                raise UnsupportedOperationError(f"HTTP Bridge does not support {operation}; no fallback was attempted")
            if operation != "new_document" and self._document is None:
                raise BridgeRemoteError("DOCUMENT_NOT_FOUND", "Call new_drawing to create a managed document")
            job = self._submit("/v1/execute", {"request_id": request_id or uuid4().hex,
                "document_id": None if operation == "new_document" else self._document,
                "expected_revision": expected_revision, "operation": operation, "args": copy_data(payload)})
            if operation == "new_document":
                if not job.document_id:
                    raise BridgeRemoteError("OUTCOME_UNKNOWN", "Created document has no session identity", request_id=job.request_id, outcome="outcome_unknown")
                self._document = job.document_id
            return copy_data(job.result)

    def execute_batch(self, operations, *, request_id=None, expected_revision=None):
        return self.execute_batch_job(operations,request_id=request_id,expected_revision=expected_revision).result

    def execute_batch_job(self, operations, *, document_id=None,request_id=None,expected_revision=None,instance_id=None):
        with self._lock:
            self._connect()
            if instance_id is not None and instance_id != self._instance:
                raise BridgeRemoteError("INSTANCE_MISMATCH", "Batch targets another Bridge instance")
            if instance_id is not None and (not request_id or expected_revision is None):
                raise ValueError("Controlled batch requires request_id and expected_revision")
            if not self._capabilities.get("atomic_batch"):
                raise UnsupportedOperationError("HTTP Bridge has no atomic batch capability")
            target=self._document if document_id is None else document_id
            if not target:
                raise BridgeRemoteError("DOCUMENT_NOT_FOUND", "Call new_drawing to create a managed document")
            if not 1 <= len(operations) <= self._capabilities.get("max_batch_operations", 200):
                raise ValueError("Invalid Bridge batch length")
            allowed = self._capabilities.get("batch_operations", ["create_layer", "draw_line", "draw_circle"])
            if any(step.get("operation") not in allowed for step in operations):
                raise UnsupportedOperationError("Operation is not advertised as batch-safe; no fallback was attempted")
            return self._submit("/v1/batch", {"request_id":request_id or uuid4().hex,
                "document_id":target, "expected_revision":expected_revision,
                "atomic":True, "operations":copy_data(operations)})

    def document_job(self, operation, args, *, instance_id, document_id=None, request_id=None, expected_revision=None):
        if operation not in {"create_working_document", "get_document_info", "save_document", "reopen_artifact"}:
            raise UnsupportedOperationError("Unsupported controlled document operation")
        with self._lock:
            self._connect()
            if instance_id != self._instance:
                raise BridgeRemoteError("INSTANCE_MISMATCH", "Read the current Bridge instance before submitting")
            if not self._capabilities.get("controlled_documents") or operation not in self._capabilities["operations"]:
                raise UnsupportedOperationError(f"HTTP Bridge does not support {operation}; no fallback was attempted")
            # Explicit APIs never alter the legacy current-document binding.
            job = self._submit("/v1/execute", {"request_id": request_id or uuid4().hex,
                "document_id": document_id, "expected_revision": expected_revision,
                "operation": operation, "args": copy_data(args)})
            try:
                model = SavedArtifactJob if operation == "save_document" else WorkingDocumentJob
                verified = model.model_validate(job.model_dump())
                if operation == "create_working_document" and (not verified.result.managed or not verified.result.output_directory):
                    raise ValueError("New working document is not managed")
                if operation == "reopen_artifact" and (verified.result.managed or verified.result.artifact is None or
                    verified.result.artifact.artifact_id != args["artifact_id"] or verified.result.source_artifact_id != args["artifact_id"]):
                    raise ValueError("Reopened artifact identity or permissions differ")
                return verified.model_dump()
            except (ValidationError, ValueError):
                raise BridgeRemoteError("OUTCOME_UNKNOWN", "Controlled document result is invalid; inspect the job before continuing",
                    request_id=job.request_id, outcome="outcome_unknown") from None

    def runtime_status(self):
        with self._lock:
            status=self.status()
            from autocad_mcp.cad.execution import support_matrix
            return {"backend":"http","state":"ready","instance_id":self._instance,
                    "capabilities":{**copy_data(self._capabilities),
                        "evidence_support":support_matrix("http",{**self._capabilities,
                            "revision_mode":status.get("revision_mode")})},
                    "bound_document_id":self._document,**status}

    def document_binding(self):
        with self._lock:
            self._connect()
            if not self._document:
                raise BridgeRemoteError("DOCUMENT_NOT_FOUND","No legacy HTTP document is bound")
            return self.document_job("get_document_info",{},instance_id=self._instance,
                                     document_id=self._document)["result"] | {"instance_id":self._instance,
                                     "revision_mode":"observed_database_events"}

    def execution_status(self, instance_id, request_id):
        with self._lock:
            # Journal lookup must not bootstrap /status on the CAD thread. A new
            # Python client must reconcile even while that thread is busy.
            if self._instance is None:
                health=self._request("GET","/v1/health")
                if health.get("protocol_version")!="1" or not health.get("instance_id"):
                    raise BridgeRemoteError("PROTOCOL_ERROR","Missing Bridge identity")
                self._instance=health["instance_id"]
            if instance_id != self._instance:
                return dict(instance_id=self._instance,request_id=request_id,status="unresolved",
                            reason="INSTANCE_MISMATCH",replay_safe=False)
            try:
                if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}",request_id):
                    raise ValueError("Invalid request ID")
                data=self._request("GET",f"/v1/requests/{request_id}",request_id=request_id)
                job=BridgeJob.model_validate({"instance_id":self._instance,**data["job"]})
                if data["request_id"]!=request_id or job.request_id!=request_id or job.instance_id!=self._instance:
                    raise ValueError("Request identity differs")
                if (not isinstance(data["operation"],str) or not data["operation"]
                        or not re.fullmatch(r"[A-Fa-f0-9]{64}",data["native_request_hash"])):
                    raise ValueError("Incomplete request identity")
                for field in ("request_document_id","source_artifact_id"):
                    identity=data[field]
                    if identity is not None and not re.fullmatch(r"[A-Za-z0-9._-]{1,128}",identity):
                        raise ValueError("Invalid recorded identity")
                revision=data["expected_revision"]
                if revision is not None and (type(revision) is not int or revision<0):
                    raise ValueError("Invalid submitted revision")
                if data["request_document_id"] and job.status=="succeeded" and job.document_id!=data["request_document_id"]:
                    raise ValueError("Recorded result document differs")
                return {**data,"contract":"bridge-request/1","job":job.model_dump()}
            except (BridgeRemoteError,ValueError,TypeError,KeyError):
                return dict(instance_id=self._instance,request_id=request_id,status="unresolved",
                            reason="RECORD_NOT_AVAILABLE_OR_INVALID",replay_safe=False)

    def query_page(self,document_id,*,entity_type="",layer="",fields=None,limit=200,cursor=""):
        if not document_id:
            raise ValueError("An explicit document_id is required")
        with self._lock:
            self._connect()
            if not self._capabilities.get("query_pagination") or "query_entities_page" not in self._capabilities["operations"]:
                raise UnsupportedOperationError("HTTP Bridge does not support pagination; no fallback was attempted")
            return self._submit("/v1/execute",{"request_id":uuid4().hex,"document_id":document_id,
                "expected_revision":None,"operation":"query_entities_page",
                "args":{"entity_type":entity_type,"layer":layer,"fields":fields,"limit":limit,"cursor":cursor}}).result

    def submit_managed(self, operation, args, *, instance_id, request_id, document_id=None, expected_revision=None):
        with self._lock:
            self._connect()
            if instance_id != self._instance:
                raise BridgeRemoteError("INSTANCE_MISMATCH", "Managed request targets another Bridge instance")
            if not self._capabilities.get("request_records"):
                raise UnsupportedOperationError("BRIDGE_UPGRADE_REQUIRED: authoritative request records are unavailable")
            if operation != "_batch" and operation not in self._capabilities["operations"]:
                raise UnsupportedOperationError("Managed operation is unavailable")
            payload = {"request_id": request_id, "document_id": document_id,
                "expected_revision": expected_revision, "client_profile": "cader-cad/1"}
            if operation == "_batch":
                payload.update(atomic=True, operations=copy_data(args["operations"]))
            else:
                payload.update(operation=operation, args=copy_data(args))
            return self._submit("/v1/batch" if operation == "_batch" else "/v1/execute", payload, allow_failure=True)

    def request_record(self, request_id):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", request_id):
            raise ValueError("Invalid Bridge request ID")
        with self._lock:
            self._connect()
            if not self._capabilities.get("request_records"):
                raise UnsupportedOperationError("BRIDGE_UPGRADE_REQUIRED: authoritative request records are unavailable")
            try:
                data = self._request("GET", f"/v1/requests/{request_id}", request_id=request_id)
            except BridgeRemoteError as error:
                error.outcome = "outcome_unknown"
                raise BridgeRemoteError(error.code, "Cannot recover authoritative request identity", request_id=request_id, outcome="outcome_unknown") from None
            try:
                if data["request_id"] != request_id or data["client_profile"] != "cader-cad/1":
                    raise ValueError("Request record identity differs")
                native = dict(data["job"])
                native.setdefault("instance_id", data["instance_id"])
                job = BridgeJob.model_validate(native)
                if job.request_id != request_id or job.instance_id != self._instance:
                    raise ValueError("Recorded job identity differs")
                if not re.fullmatch(r"[A-Fa-f0-9]{64}", data["native_request_hash"]):
                    raise ValueError("Missing native request hash")
                return {**data, "job": job}
            except (KeyError, TypeError, ValueError, ValidationError):
                raise BridgeRemoteError("PROTOCOL_ERROR", "Invalid authoritative request record", request_id=request_id, outcome="outcome_unknown") from None

    def query_page_guarded(self, instance_id, document_id, expected_revision, *, limit=1000, cursor=""):
        with self._lock:
            self._connect()
            if instance_id != self._instance:
                raise BridgeRemoteError("INSTANCE_MISMATCH", "Query targets another Bridge instance")
            if not self._capabilities.get("query_pagination"):
                raise UnsupportedOperationError("Guarded pagination is unavailable")
            job = self._submit("/v1/execute", {"request_id": uuid4().hex, "document_id": document_id,
                "expected_revision": expected_revision, "operation": "query_entities_page",
                "args": {"entity_type": "", "layer": "", "fields": None, "limit": limit, "cursor": cursor}})
            if job.revision != expected_revision or job.result.get("revision") != expected_revision or job.result.get("document_id") != document_id:
                raise BridgeRemoteError("REVISION_CONFLICT", "Query revision/document changed")
            return copy_data(job.result)

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                self._client.close()
