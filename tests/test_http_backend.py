"""HTTP transport contracts; fake Bridge tests do not establish CAD correctness."""
import json

import httpx
import pytest
from pydantic import ValidationError

from autocad_mcp.config import Config, HTTPConfig
from autocad_mcp.cad.backends.http_backend import HTTPBackend, BridgeRemoteError
from autocad_mcp.cad.errors import BackendClosedError, UnsupportedOperationError

TOKEN = "unit-test-token-" * 4


def test_explicit_batch_returns_identity_without_changing_legacy_binding(setup_backend):
    backend,bridge=setup_backend
    def response(data):
        return dict(instance_id=bridge.instance,request_id=data['request_id'],status='succeeded',
                    document_id=data['document_id'],revision=9,result=[1])
    bridge.post_response=response
    job=backend.execute_batch_job([{'id':'one','operation':'draw_line','args':{}}],
                                 document_id='doc-b',request_id='batch-one',expected_revision=8)
    assert job.document_id=='doc-b' and job.revision==9 and job.result==[1]
    sent=json.loads(bridge.calls[-1].content)
    assert sent['document_id']=='doc-b' and sent['expected_revision']==8 and sent['atomic']
    assert backend.runtime_status()['bound_document_id']=='doc-a'
    assert sum(c.method=='POST' for c in bridge.calls)==1


def test_pagination_capability_and_explicit_document_payload(setup_backend):
    backend,bridge=setup_backend
    with pytest.raises(UnsupportedOperationError,match='no fallback'):
        backend.query_page('doc-b')
    assert all(c.method=='GET' for c in bridge.calls)
    # A fresh backend is required to renegotiate changed capabilities.
    bridge.query_pagination=True
    bridge.operations.append('query_entities_page')
    backend._capabilities=None
    bridge.post_response=lambda data:dict(instance_id=bridge.instance,request_id=data['request_id'],
        status='succeeded',document_id='doc-b',result={'items':[],'next_cursor':None})
    result=backend.query_page('doc-b',entity_type='AcDbLine',layer='Fixture',fields=['handle'],limit=5,cursor='opaque')
    assert result['items']==[]
    data=json.loads(bridge.calls[-1].content)
    assert data['document_id']=='doc-b'
    assert data['operation']=='query_entities_page'
    assert data['args']==dict(entity_type='AcDbLine',layer='Fixture',fields=['handle'],limit=5,cursor='opaque')
    assert backend.runtime_status()['bound_document_id']=='doc-a'


def test_explicit_batch_lost_response_does_not_replay(setup_backend):
    backend,bridge=setup_backend
    bridge.timeout_post=True
    with pytest.raises(BridgeRemoteError) as failure:
        backend.execute_batch_job([{'id':'one','operation':'draw_line','args':{}}],
                                  document_id='doc-b',request_id='uncertain-batch')
    assert failure.value.code=='OUTCOME_UNKNOWN' and failure.value.request_id=='uncertain-batch'
    assert sum(c.method=='POST' for c in bridge.calls)==1

def test_job_status_rejects_a_different_request_identity(setup_backend):
    backend,bridge=setup_backend
    bridge.job_response=lambda _:bridge.envelope('someone-else')
    with pytest.raises(BridgeRemoteError) as failure:
        backend.get_job('my-request')
    assert failure.value.code=='PROTOCOL_ERROR'
    assert failure.value.outcome=='outcome_unknown'
    assert all(c.method=='GET' for c in bridge.calls)


class MockBridge:
    def __init__(self):
        self.calls = []
        self.protocol = "1"
        self.instance = "instance-a"
        self.operations = ["new_document", "draw_line", "query_entities"]
        self.post_response = None
        self.job_response = None
        self.timeout_post = False
        self.query_pagination = False

    def envelope(self, request_id, **values):
        return dict(instance_id=self.instance, request_id=request_id,
                    status="succeeded", document_id="doc-a", result=123, **values)

    def __call__(self, request):
        self.calls.append(request)
        assert request.headers["authorization"] == "Bearer " + TOKEN
        path = request.url.path
        if path == "/v1/health":
            return httpx.Response(200, json={"instance_id":self.instance,
                "protocol_version":self.protocol,"status":"ready"})
        if path == "/v1/capabilities":
            return httpx.Response(200, json={"instance_id":self.instance,
                "protocol_version":"1","operations":self.operations,"atomic_batch":True,
                "query_pagination":self.query_pagination,"controlled_documents":getattr(self,"controlled_documents",False)})
        if path == "/v1/status":
            return httpx.Response(200, json={"instance_id":self.instance,"request_id":"status",
                "status":"succeeded","result":{"active_document_id":"doc-a","documents":[]}})
        if request.method == "POST":
            if self.timeout_post:
                raise httpx.ReadTimeout("Simulated lost write response", request=request)
            data = json.loads(request.content)
            if self.post_response:
                return httpx.Response(202, json=self.post_response(data))
            return httpx.Response(200, json=self.envelope(data["request_id"]))
        if path.startswith("/v1/jobs/"):
            return httpx.Response(200, json=self.job_response(path.rsplit("/",1)[-1]))
        raise AssertionError(f"Unexpected HTTP request {request.method} {path}")


@pytest.fixture
def setup_backend(monkeypatch):
    monkeypatch.setenv("AUTOCAD_BRIDGE_TOKEN", TOKEN)
    bridge = MockBridge()
    client = httpx.Client(base_url="http://127.0.0.1:8765",
                         transport=httpx.MockTransport(bridge))
    backend = HTTPBackend(Config(cad_type="AutoCAD",prog_id="test",backend="http"),
                          client=client)
    yield backend, bridge
    backend.close()


def test_lazy_handshake_and_legacy_payload(setup_backend):
    backend, bridge = setup_backend
    assert bridge.calls == []
    assert backend.execute("draw_line", {"start":(0,0,0),"end":(1,0,0)}) == 123
    sent = json.loads(bridge.calls[-1].content)
    assert sent["operation"] == "draw_line"
    assert sent["document_id"] == "doc-a"
    assert sent["args"] == {"start":[0,0,0],"end":[1,0,0]}
    assert len(sent["request_id"]) == 32


def test_capability_error_never_posts_or_falls_back(setup_backend):
    backend, bridge = setup_backend
    with pytest.raises(UnsupportedOperationError, match="no fallback"):
        backend.execute("draw_text", {"position":(0,0,0),"text":"x","height":1})
    assert all(call.method == "GET" for call in bridge.calls)


def test_protocol_mismatch_stops_before_status_or_post(setup_backend):
    backend, bridge = setup_backend
    bridge.protocol = "99"
    with pytest.raises(BridgeRemoteError, match="PROTOCOL_ERROR"):
        backend.execute("query_entities", {})
    assert len(bridge.calls) == 1


def test_queued_job_is_polled_without_resubmission(setup_backend):
    backend, bridge = setup_backend
    bridge.post_response = lambda data: {
        "instance_id":"instance-a","request_id":data["request_id"],"status":"queued"}
    bridge.job_response = bridge.envelope
    assert backend.execute("draw_line", {"start":[0,0,0],"end":[1,0,0]},
                           request_id="stable-request") == 123
    assert sum(call.method == "POST" for call in bridge.calls) == 1
    assert bridge.calls[-1].url.path == "/v1/jobs/stable-request"


def test_lost_write_response_reports_unknown_and_never_retries(setup_backend):
    backend, bridge = setup_backend
    bridge.timeout_post = True
    with pytest.raises(BridgeRemoteError) as failure:
        backend.execute("draw_line", {"start":[0,0,0],"end":[1,0,0]},
                        request_id="uncertain")
    assert failure.value.code == "OUTCOME_UNKNOWN"
    assert failure.value.request_id == "uncertain"
    assert failure.value.outcome == "outcome_unknown"
    assert sum(call.method == "POST" for call in bridge.calls) == 1


def test_poll_failure_cannot_claim_the_write_was_not_executed(setup_backend):
    backend, bridge = setup_backend
    bridge.post_response = lambda data: {
        "instance_id":"instance-a","request_id":data["request_id"],"status":"queued"}
    def lost_poll(request_id):
        raise httpx.ReadTimeout("Connection lost while querying accepted write")
    bridge.job_response = lost_poll
    with pytest.raises(BridgeRemoteError) as failure:
        backend.execute("draw_line", {"start":[0,0,0],"end":[1,0,0]})
    assert failure.value.code == "OUTCOME_UNKNOWN"
    assert failure.value.outcome == "outcome_unknown"
    assert sum(call.method == "POST" for call in bridge.calls) == 1


@pytest.mark.parametrize("fault", ["instance", "request", "document", "schema"])
def test_untrusted_job_identity_or_envelope_is_rejected(setup_backend, fault):
    backend, bridge = setup_backend
    def response(data):
        result = bridge.envelope(data["request_id"])
        if fault == "instance": result["instance_id"] = "restarted"
        if fault == "request": result["request_id"] = "someone-else"
        if fault == "document": result["document_id"] = "wrong-drawing"
        if fault == "schema": result["status"] = "made-up"
        return result
    bridge.post_response = response
    with pytest.raises(BridgeRemoteError) as failure:
        backend.execute("query_entities", {})
    assert failure.value.code == "OUTCOME_UNKNOWN"


def test_new_document_binds_subsequent_requests(setup_backend):
    backend, bridge = setup_backend
    def response(data):
        value = bridge.envelope(data["request_id"])
        value["document_id"] = "new-session"
        value["result"] = "New.dwg"
        return value
    bridge.post_response = response
    assert backend.execute("new_document", {}) == "New.dwg"
    assert json.loads(bridge.calls[-1].content)["document_id"] is None
    backend.execute("query_entities", {})
    assert json.loads(bridge.calls[-1].content)["document_id"] == "new-session"


def test_atomic_failure_preserves_outcome(setup_backend):
    backend, bridge = setup_backend
    def response(data):
        return {"instance_id":"instance-a","request_id":data["request_id"],
            "status":"rolled_back","document_id":"doc-a",
            "error":{"code":"INVALID_ARGUMENT","message":"Invalid radius",
                     "outcome":"rolled_back","failed_operation_id":"circle"}}
    bridge.post_response = response
    with pytest.raises(BridgeRemoteError) as failure:
        backend.execute_batch([{"id":"circle","operation":"draw_circle",
                                "args":{"center":[0,0,0],"radius":-1}}])
    assert failure.value.outcome == "rolled_back"
    assert bridge.calls[-1].url.path == "/v1/batch"


def test_missing_secret_never_connects(setup_backend, monkeypatch):
    backend, bridge = setup_backend
    monkeypatch.delenv("AUTOCAD_BRIDGE_TOKEN")
    with pytest.raises(BridgeRemoteError, match="UNAUTHORIZED"):
        backend.capabilities()
    assert not bridge.calls


def test_close_does_not_touch_cad_and_rejects_execution(setup_backend):
    backend, bridge = setup_backend
    backend.close()
    with pytest.raises(BackendClosedError):
        backend.execute("query_entities", {})
    assert not bridge.calls


@pytest.mark.parametrize("url", ["http://example.test:8765","https://127.0.0.1:8765",
    "http://localhost:8765","http://127.0.0.1:8765/path","http://a:b@127.0.0.1:8765",
    "http://127.0.0.1:8765?token=secret","http://127.0.0.1:80"])
def test_bridge_config_rejects_nonlocal_or_ambiguous_urls(url):
    with pytest.raises(ValidationError):
        HTTPConfig(base_url=url)
