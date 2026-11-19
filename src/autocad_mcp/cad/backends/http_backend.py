"""Authenticated loopback Bridge client. Never retries/replays a write request."""
import os
import re
from threading import RLock
import time
from uuid import uuid4

import httpx
from pydantic import ValidationError

from autocad_mcp.config import Config
from autocad_mcp.cad.backends.base import copy_data, operation_signature
from autocad_mcp.cad.errors import BackendClosedError, BackendError, UnsupportedOperationError
from autocad_mcp.cad.models import BridgeJob

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

    def _submit(self, path, payload):
        request_id = payload["request_id"]
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", request_id):
            raise ValueError("Invalid Bridge request ID")
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
                if job.status != "succeeded":
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

    def execute_batch_job(self, operations, *, document_id=None,request_id=None,expected_revision=None):
        with self._lock:
            self._connect()
            if not self._capabilities.get("atomic_batch"):
                raise UnsupportedOperationError("HTTP Bridge has no atomic batch capability")
            target=self._document if document_id is None else document_id
            if not target:
                raise BridgeRemoteError("DOCUMENT_NOT_FOUND", "Call new_drawing to create a managed document")
            if not 1 <= len(operations) <= self._capabilities.get("max_batch_operations", 200):
                raise ValueError("Invalid Bridge batch length")
            return self._submit("/v1/batch", {"request_id":request_id or uuid4().hex,
                "document_id":target, "expected_revision":expected_revision,
                "atomic":True, "operations":copy_data(operations)})

    def runtime_status(self):
        with self._lock:
            status=self.status()
            return {"backend":"http","state":"ready","instance_id":self._instance,
                    "capabilities":copy_data(self._capabilities),"bound_document_id":self._document,**status}

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

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                self._client.close()
