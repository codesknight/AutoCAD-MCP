"""Faults at real adapter/native boundaries with plain fixtures; no CAD claims."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from autocad_mcp import state
from autocad_mcp.cad.backends.com_backend import COMBackend, COMSession
from autocad_mcp.cad.connection import CADConnection, CADDocumentChangedError
from autocad_mcp.cad.controller import CADController
from autocad_mcp.cad.execution import ExecutionJournal, support_matrix
from autocad_mcp.cad.query import CADQuery
from autocad_mcp.config import Config
from autocad_mcp.server import mcp

CFG = Config(cad_type="AutoCAD",prog_id="offline")
ARGS = dict(start=[0,0,0],end=[10,0,0])


class Space(list):
    def __init__(self):
        super().__init__()
        self.calls = 0
        self.lose_ack = False
        self.started = self.finish = None

    def AddLine(self, start, end):
        self.calls += 1
        if self.started:
            self.started.set()
            assert self.finish.wait(5)
        entity = SimpleNamespace(ObjectID=self.calls,Layer="0",ObjectName="AcDbLine")
        entity.Delete = lambda:self.remove(entity)
        self.append(entity)
        if self.lose_ack:
            raise RuntimeError("native effect happened but ACK was lost")
        return entity


class Documents:
    def __init__(self, *docs):self.items=list(docs)
    @property
    def Count(self):return len(self.items)
    def Item(self,i):return self.items[i]


def fixture_session():
    conn=CADConnection(CFG)
    doc=SimpleNamespace(Name="same.dwg",ReadOnly=False,ModelSpace=Space())
    conn.app=SimpleNamespace(ActiveDocument=doc,Documents=Documents(doc))
    conn.document=doc;conn.model_space=doc.ModelSpace
    conn._owned_ids.add(conn.document_id(doc))
    session=COMSession.__new__(COMSession)
    session.connection=conn;session.controller=CADController(conn);session.query=CADQuery(conn)
    return session


@pytest.fixture
def fixture_backend():
    session=fixture_session()
    backend=COMBackend(CFG,session_factory=lambda _:session)
    binding=backend.document_binding()
    yield backend,session,binding
    backend.close()


def submit(backend,binding,request_id="line",**extra):
    return backend.execute_evidenced("draw_line",ARGS,request_id=request_id,
        instance_id=binding["instance_id"],document_id=binding["document_id"],**extra)


def test_same_name_switch_rejected_before_mutation(fixture_backend):
    backend,session,binding=fixture_backend
    conn=session.connection
    other=SimpleNamespace(Name="same.dwg",ReadOnly=False,ModelSpace=Space())
    conn.app.Documents.items.append(other);conn.app.ActiveDocument=other
    answer=submit(backend,binding)
    assert answer["receipt"]["stage"]=="not_dispatched"
    assert not answer["receipt"]["native_invoked"]
    assert conn.model_space.calls==other.ModelSpace.calls==0
    assert conn.document_id(other)!=binding["document_id"]


def test_saveas_label_change_preserves_binding(fixture_backend):
    backend,session,binding=fixture_backend
    session.connection.document.Name="renamed.dwg"
    updated=backend.document_binding()
    assert updated["document_id"]==binding["document_id"]
    assert submit(backend,binding)["receipt"]["status"]=="succeeded"


def test_closed_identity_cannot_adopt_reopened_same_name(fixture_backend):
    backend,session,binding=fixture_backend
    conn=session.connection;old=conn.document
    new=SimpleNamespace(Name=old.Name,ReadOnly=False,ModelSpace=Space())
    conn.app.Documents.items=[new];conn.app.ActiveDocument=new
    with pytest.raises(CADDocumentChangedError):conn.ensure_document()
    conn.document=new;conn.model_space=new.ModelSpace
    assert backend.document_binding()["document_id"]!=binding["document_id"]
    assert submit(backend,binding)["receipt"]["stage"]=="not_dispatched"


def test_ack_then_post_observation_busy_keeps_native_ack(fixture_backend):
    backend,session,binding=fixture_backend
    real=session.connection.binding
    reads=[]
    def busy():
        reads.append(1)
        if len(reads)==2:raise RuntimeError("RPC_E_CALL_REJECTED reading after ACK")
        return real()
    session.connection.binding=busy
    answer=submit(backend,binding)
    receipt=answer["receipt"]
    assert receipt["stage"]=="observation_failed"
    assert receipt["native_acknowledged"] and receipt["affected_entities"]["created"]==["1"]
    assert not receipt["affected_entities"]["complete"]
    assert len(session.connection.model_space)==1
    assert backend.execution_status(binding["instance_id"],"line")==receipt
    assert submit(backend,binding)["receipt"]==receipt
    assert session.connection.model_space.calls==1


def test_no_ack_stays_unknown_even_when_effect_exists_and_not_replayed(fixture_backend):
    backend,session,binding=fixture_backend
    session.connection.model_space.lose_ack=True
    receipt=submit(backend,binding)["receipt"]
    assert receipt["stage"]=="result_unknown" and receipt["native_invoked"]
    assert not receipt["native_acknowledged"]
    assert len(session.connection.model_space)==1
    assert submit(backend,binding)["receipt"]==receipt
    assert session.connection.model_space.calls==1


def test_acknowledged_creation_is_not_deleted_when_id_observation_fails(fixture_backend):
    backend,session,binding=fixture_backend
    space=session.connection.model_space;deletes=[]
    class Entity:
        @property
        def ObjectID(self):raise RuntimeError("observation unavailable")
        def Delete(self):deletes.append(1)
    def add(*unused):
        e=Entity();space.append(e);return e
    space.AddLine=add
    receipt=submit(backend,binding)["receipt"]
    assert receipt["stage"]=="observation_failed" and receipt["native_acknowledged"]
    assert len(space)==1 and not deletes
    assert receipt["affected_entities"]["complete"] is False


def test_edit_effects_use_the_document_scoped_target_and_return_complete_sets(fixture_backend):
    backend,session,binding=fixture_backend
    submit(backend,binding)
    space=session.connection.model_space
    session.connection.document.ObjectIdToObject=lambda key:next(e for e in space if e.ObjectID==key)
    space[0].Move=lambda *unused:None
    for operation,args,kind in [("move_entity",dict(object_id=1,offset=[1,2,0]),"modified"),
                                ("delete_entity",dict(object_id=1),"deleted")]:
        receipt=backend.execute_evidenced(operation,args,request_id=operation,
            instance_id=binding["instance_id"],document_id=binding["document_id"])["receipt"]
        assert receipt["status"]=="succeeded" and receipt["affected_entities"][kind]==["1"]
        assert receipt["affected_entities"]["complete"]
    assert len(space)==0


def test_foreign_entity_id_cannot_mutate_another_same_name_document(fixture_backend):
    backend,session,binding=fixture_backend
    moved=[]
    other=SimpleNamespace(Name="same.dwg",ReadOnly=False,ModelSpace=Space())
    entity=SimpleNamespace(Document=other,Move=lambda *unused:moved.append(1))
    session.connection.document.ObjectIdToObject=lambda key:entity
    result=backend.execute_evidenced("move_entity",dict(object_id=999,offset=[1,0,0]),request_id="foreign-entity",
        instance_id=binding["instance_id"],document_id=binding["document_id"])
    assert result["receipt"]["stage"]=="not_dispatched" and not moved


def test_binding_cache_cannot_be_changed_by_the_caller(fixture_backend):
    backend,_,binding=fixture_backend
    value=backend.document_binding();value["document_id"]="forged"
    assert backend.runtime_status()["bound_document_id"]==binding["document_id"]


def test_explicit_binding_connection_does_not_launch_a_missing_cad(monkeypatch):
    from autocad_mcp.cad import connection
    def missing(*unused):raise RuntimeError("no running CAD")
    monkeypatch.setattr(connection.win32com.client,"GetActiveObject",missing)
    monkeypatch.setattr(connection.win32com.client,"Dispatch",lambda *unused:pytest.fail("unexpected CAD launch"))
    with pytest.raises(connection.CADConnectionError):CADConnection(CFG).connect(allow_launch=False)


def test_attach_only_observation_does_not_change_existing_window_visibility(monkeypatch):
    from autocad_mcp.cad import connection
    writes=[]
    class App:
        Documents=Documents()
        @property
        def Visible(self):return False
        @Visible.setter
        def Visible(self,value):writes.append(value)
    monkeypatch.setattr(connection.win32com.client,"GetActiveObject",lambda _:App())
    conn=CADConnection(CFG);conn.connect(allow_launch=False)
    assert conn.app.Visible is False and not writes


@pytest.mark.parametrize("mismatch",["document","instance","readonly","arguments","point_shape","numeric_string_nan","unmanaged"])
def test_rejected_inputs_cannot_mutate(fixture_backend,mismatch):
    backend,session,binding=fixture_backend
    args=dict(ARGS);instance=binding["instance_id"];doc=binding["document_id"]
    if mismatch=="document":doc="wrong"
    if mismatch=="instance":instance="wrong"
    if mismatch=="readonly":session.connection.document.ReadOnly=True
    if mismatch=="arguments":args.pop("end")
    if mismatch=="point_shape":args["start"]=[0,0]
    if mismatch=="numeric_string_nan":args["start"]=["NaN",0,0]
    if mismatch=="unmanaged":session.connection._owned_ids.clear()
    receipt=backend.execute_evidenced("draw_line",args,request_id="reject",
        instance_id=instance,document_id=doc)["receipt"]
    assert receipt["stage"]=="not_dispatched" and not receipt["native_invoked"]
    assert session.connection.model_space.calls==0


def test_conflicting_duplicate_preserves_original_and_dispatches_once(fixture_backend):
    backend,session,binding=fixture_backend
    original=submit(backend,binding)["receipt"]
    with pytest.raises(ValueError,match="REQUEST_ID_CONFLICT"):
        backend.execute_evidenced("draw_line",dict(start=[0,0,0],end=[99,0,0]),
            request_id="line",instance_id=binding["instance_id"],document_id=binding["document_id"])
    assert backend.execution_status(binding["instance_id"],"line")==original
    assert session.connection.model_space.calls==1


def test_unadvertised_operation_is_explicitly_unsupported_without_dispatch(fixture_backend):
    backend,session,binding=fixture_backend
    result=backend.execute_evidenced("draw_hatch",{},request_id="unsupported",instance_id=binding["instance_id"],document_id=binding["document_id"])
    receipt=result["receipt"]
    assert receipt["error"]["type"]=="UnsupportedOperationError"
    assert receipt["stage"]=="not_dispatched" and session.connection.model_space.calls==0


def test_pending_lookup_is_read_only_and_does_not_wait_for_sta(fixture_backend):
    backend,session,binding=fixture_backend
    space=session.connection.model_space;space.started=Event();space.finish=Event()
    with ThreadPoolExecutor() as pool:
        future=pool.submit(submit,backend,binding)
        assert space.started.wait(5)
        pending=backend.execution_status(binding["instance_id"],"line")
        assert pending["stage"]=="dispatching" and pending["status"]=="pending"
        assert submit(backend,binding)["receipt"]["status"]=="pending"
        space.finish.set()
        assert future.result(timeout=5)["receipt"]["status"]=="succeeded"
    assert space.calls==1


def test_backend_restart_and_missing_record_never_authorize_replay(fixture_backend):
    backend,_,binding=fixture_backend
    submit(backend,binding)
    fresh=COMBackend(CFG)
    try:
        for instance,request in [(binding["instance_id"],"line"),(fresh.instance_id,"line")]:
            result=fresh.execution_status(instance,request)
            assert result["status"]=="unresolved" and result["replay_safe"] is False
        assert fresh._thread is None
    finally:fresh.close()


def test_journal_expiry_capacity_and_copy_isolation():
    now=[0];journal=ExecutionJournal("i",capacity=1,ttl=10,clock=lambda:now[0])
    assert journal.accept("r","draw_line",ARGS,"i","d")
    with pytest.raises(ValueError,match="FULL"):journal.accept("s","draw_line",ARGS,"i","d")
    copy=journal.lookup("i","r");copy["native_actions"].append({})
    assert not journal.lookup("i","r")["native_actions"]
    now[0]=100
    assert journal.lookup("i","r")["status"]=="pending" # Pending never evicted.
    journal.update("r",status="failed");now[0]=110
    assert journal.lookup("i","r")["status"]=="unresolved"
    assert journal.accept("s","draw_line",ARGS,"i","d")


def test_capability_matrix_does_not_invent_revision_or_mapping():
    com=support_matrix("com")
    assert com["revision"]==dict(authoritative=False,manual_edits_observed=False,mode="unsupported",value=None)
    assert com["capture"]["pixel_to_cad"]=="unavailable"
    assert not com["batch"]["atomic"] and com["readonly_reopen"]["supported"]
    assert com["file_artifacts"]["source_revision_authoritative"] is False
    assert not support_matrix("http")["revision"]["authoritative"]
    http=support_matrix("http",dict(revision_mode="observed_database_events",query_pagination=True,atomic_batch=True,controlled_documents=True))
    assert http["revision"]["manual_edits_observed"] and http["query"]["revision_bound"]


@pytest.mark.parametrize("fault",[None,"missing","wrong_request","wrong_instance","malformed"])
def test_fresh_http_record_lookup_never_calls_cad_status_even_when_busy(monkeypatch,fault):
    from autocad_mcp.cad.backends.http_backend import HTTPBackend
    monkeypatch.setenv("AUTOCAD_BRIDGE_TOKEN","unit-token-"*5)
    requests=[]
    def transport(request):
        requests.append(request)
        if request.url.path=="/v1/health":
            return httpx.Response(200,json=dict(instance_id="bridge",protocol_version="1",status="ready"))
        assert request.url.path=="/v1/requests/r" and request.method=="GET"
        if fault=="missing":return httpx.Response(404,json=dict(instance_id="bridge",error=dict(code="JOB_NOT_FOUND")))
        job=dict(request_id="else" if fault=="wrong_request" else "r",status="succeeded",document_id="doc",revision=9,result=1)
        if fault=="wrong_instance":job["instance_id"]="else"
        if fault=="malformed":job["status"]="invalid"
        return httpx.Response(200,json=dict(instance_id="bridge",request_id="r",operation="draw_line",
            request_document_id="doc",expected_revision=7,source_artifact_id=None,client_profile=None,
            native_request_hash="a"*64,job=job))
    client=httpx.Client(base_url="http://127.0.0.1:8765",transport=httpx.MockTransport(transport))
    backend=HTTPBackend(CFG.model_copy(update={"backend":"http"}),client=client)
    try:
        result=backend.execution_status("bridge","r")
        if fault:assert result["status"]=="unresolved" and result["replay_safe"] is False
        else:assert result["job"]["revision"]==9 and result["operation"]=="draw_line"
        assert [r.url.path for r in requests]==["/v1/health","/v1/requests/r"]
    finally:backend.close()


def test_actual_mcp_receipt_is_error_but_preserves_correlated_facts(fixture_backend,monkeypatch):
    backend,session,binding=fixture_backend
    session.connection.model_space.lose_ack=True
    state.close_backend();monkeypatch.setattr(state,"create_backend",lambda _:backend)
    async def run():
        async with create_connected_server_and_client_session(mcp) as client:
            result=await client.call_tool("execute_observed_operation",dict(instance_id=binding["instance_id"],
                document_id=binding["document_id"],request_id="mcp-lost",operation="draw_line",arguments=ARGS))
            assert result.isError
            receipt=result.structuredContent["receipt"]
            assert receipt["request_id"]=="mcp-lost" and receipt["stage"]=="result_unknown"
            queried=await client.call_tool("get_execution_status",dict(instance_id=binding["instance_id"],request_id="mcp-lost"))
            assert not queried.isError and queried.structuredContent==receipt
    asyncio.run(run());state.close_backend()


@pytest.mark.parametrize("failures", [0, 2, 100])
def test_new_document_label_uses_safe_property_read_without_repeating_add(failures):
    from autocad_mcp.cad.execution import native_action
    calls = {"add": 0, "name": 0}

    class Ole:
        def GetIDsOfNames(self, name):
            assert name == "Name"
            return 1

        def Invoke(self, *args):
            calls["name"] += 1
            if calls["name"] <= failures:
                raise AttributeError("fresh wrapper metadata unavailable")
            return "fresh.dwg"

    class Document:
        _oleobj_ = Ole()

        @property
        def Name(self):
            raise AssertionError("Unsafe wrapper property must not be used")

    def create():
        def add():
            calls["add"] += 1
        native_action("Documents.Add", add)

    binding = dict(instance_id="fixture", document_id="fresh", name="fresh.dwg",
                   managed=True, read_only=False, revision=None, revision_mode="unsupported")
    session = COMSession.__new__(COMSession)
    session.connection = SimpleNamespace(new_document=create, document=Document(),
                                         binding=lambda: binding, disconnect=lambda: None)
    backend = COMBackend(CFG, session_factory=lambda _: session)
    try:
        result = backend.execute_evidenced("new_document", {}, request_id="fresh",
                                          instance_id=backend.instance_id)
        receipt = result["receipt"]
        assert calls["add"] == 1
        assert receipt["native_acknowledged"] is True
        assert len(receipt["native_actions"]) == 1
        if failures < 20:
            assert receipt["status"] == "succeeded"
            assert result["result"] == "fresh.dwg"
            assert receipt["result_document_id"] == "fresh"
        else:
            assert receipt["stage"] == "observation_failed"
            assert receipt["result_document_id"] is None
            assert calls["name"] == 20
    finally:
        backend.close()
