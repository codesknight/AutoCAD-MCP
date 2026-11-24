"""Offline native-boundary fault injection; never attach to real AutoCAD."""
import asyncio
from types import SimpleNamespace

import pytest
from autocad_mcp import state
from autocad_mcp.cad import connection
from autocad_mcp.cad.backends.com_backend import COMSession
from autocad_mcp.cad.connection import CADConnection, CADNewDocumentError
from autocad_mcp.config import Config
from autocad_mcp.tools.document_tools import register
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult


class Documents:
    def __init__(self, app, names=()):
        self.app = app
        self.items = [SimpleNamespace(Name=name, ModelSpace=object()) for name in names]
        self.calls = self.lookups = 0
        self.fail_lookups = 0
        self.after_create_error = False
        if self.items:
            app.ActiveDocument = self.items[-1]

    @property
    def Count(self):
        return len(self.items)

    def Item(self, index):
        return self.items[index]

    @property
    def Add(self):
        self.lookups += 1
        if self.lookups <= self.fail_lookups:
            raise AttributeError("<unknown>.Add")
        return self.create

    def create(self, *args):
        self.calls += 1
        doc = SimpleNamespace(Name=f"fixture-new-{self.calls}", ModelSpace=object())
        self.items.append(doc)
        self.app.ActiveDocument = doc
        if self.after_create_error:
            raise AttributeError("injected failure after native side effect")
        return object()  # Do not trust an unresolved Add return wrapper.


def setup(monkeypatch, names=()):
    app = SimpleNamespace()
    app.Documents = Documents(app, names)
    monkeypatch.setattr(connection.win32com.client, "GetActiveObject", lambda _: app)
    monkeypatch.setattr(connection.pythoncom, "PumpWaitingMessages", lambda: None)
    monkeypatch.setattr(connection.time, "sleep", lambda _: None)
    cfg = Config(cad_type="AutoCAD", prog_id="fixture.only", connect_timeout=1)
    conn = CADConnection(cfg)
    return app, conn, cfg


def test_connect_without_documents_never_creates_and_first_new_document_creates_once(monkeypatch):
    app, conn, cfg = setup(monkeypatch)
    conn.connect()
    assert app.Documents.calls == 0
    assert conn.document is conn.model_space is None
    session = COMSession(cfg)
    assert app.Documents.calls == 0
    assert session.execute("new_document", {}) == "fixture-new-1"
    assert app.Documents.calls == 1
    session.close()


def test_lookup_can_retry_without_repeating_native_add_or_binding_the_old_document(monkeypatch):
    app, conn, _ = setup(monkeypatch, ["user-existing"])
    conn.connect()
    app.Documents.fail_lookups = 2
    conn.new_document()
    assert app.Documents.lookups == 3
    assert app.Documents.calls == 1
    assert conn.document.Name == "fixture-new-1"
    assert app.Documents.items[0].Name == "user-existing"


def test_native_dispid_path_bypasses_unresolved_dynamic_method_map(monkeypatch):
    app, conn, _ = setup(monkeypatch)
    documents = app.Documents
    lookups = []

    def get_id(name):
        lookups.append(name)
        if len(lookups) == 1:
            raise AttributeError("injected transient metadata failure")
        return 42

    def invoke(dispid, lcid, flags, result_wanted, *args):
        assert (dispid, lcid, flags, result_wanted) == (42, 0, connection.pythoncom.DISPATCH_METHOD, True)
        return documents.create(*args)

    documents._oleobj_ = SimpleNamespace(GetIDsOfNames=get_id, Invoke=invoke)
    documents.fail_lookups = 100
    conn.connect()
    conn.new_document()
    assert lookups == ["Add", "Add"]
    assert documents.lookups == 0
    assert documents.calls == 1


def test_exhausted_preflight_is_explicit_no_invocation_and_preserves_old_binding(monkeypatch):
    app, conn, _ = setup(monkeypatch, ["user-existing"])
    conn.connect()
    conn.config.connect_timeout = 0
    old = conn.document
    app.Documents.fail_lookups = 100
    with pytest.raises(CADNewDocumentError) as caught:
        conn.new_document()
    evidence = caught.value.evidence
    assert evidence["stage"] == "preflight"
    assert evidence["native_invoked"] is evidence["native_acknowledged"] is False
    assert evidence["implicit_creates"] == 0
    assert "<unknown>.Add" in evidence["exception"]["traceback"]
    assert app.Documents.calls == 0
    assert conn.document is old


def test_failure_after_native_side_effect_is_never_replayed_or_claimed_not_invoked(monkeypatch):
    app, conn, _ = setup(monkeypatch)
    conn.connect()
    app.Documents.after_create_error = True
    with pytest.raises(CADNewDocumentError) as caught:
        conn.new_document()
    assert app.Documents.calls == 1
    assert app.Documents.Count == 1
    assert caught.value.evidence["native_invoked"] is True
    assert caught.value.evidence["native_acknowledged"] is False
    assert conn.document is conn.model_space is None


def test_acknowledged_add_with_failed_new_binding_is_unknown_without_second_add(monkeypatch):
    app, conn, _ = setup(monkeypatch, ["user-existing"])
    conn.connect()

    def wait(*args, **kwargs):
        assert kwargs["excluded_names"] == {"user-existing"}
        raise RuntimeError("injected binding failure")

    monkeypatch.setattr(conn, "_wait_for_document", wait)
    with pytest.raises(CADNewDocumentError) as caught:
        conn.new_document()
    assert app.Documents.calls == 1
    assert caught.value.evidence["native_invoked"] is True
    assert caught.value.evidence["native_acknowledged"] is True
    assert caught.value.evidence["stage"] == "binding"
    assert conn.document is None


def test_wait_cannot_adopt_old_active_document_after_an_acknowledgement(monkeypatch):
    app, conn, _ = setup(monkeypatch, ["user-existing"])
    conn.connect()

    def no_new_document(*args):
        app.Documents.calls += 1
        return None

    monkeypatch.setattr(app.Documents, "create", no_new_document)
    clock = iter([0, 0, 2])
    monkeypatch.setattr(connection.time, "time", lambda: next(clock))
    with pytest.raises(CADNewDocumentError) as caught:
        conn.new_document()
    assert app.Documents.calls == 1
    assert caught.value.evidence["stage"] == "binding"
    assert caught.value.evidence["native_invoked"] is True
    assert conn.document is conn.model_space is None


def test_mcp_returns_correlated_native_evidence_and_keeps_success_name_compatible(monkeypatch):
    mcp = FastMCP("native-boundary-fixture")
    register(mcp)

    def fail():
        try:
            raise AttributeError("<unknown>.Add")
        except AttributeError as exc:
            raise CADNewDocumentError("preflight", False, False, [], exc) from exc

    monkeypatch.setattr(state, "new_document", fail)
    result = asyncio.run(mcp.call_tool("new_drawing", {"request_id": "fixture-request"}))
    assert isinstance(result, CallToolResult) and result.isError
    assert result.structuredContent["request_id"] == "fixture-request"
    assert result.structuredContent["native_invoked"] is False
    monkeypatch.setattr(state, "new_document", lambda: "fixture-new")
    result = asyncio.run(mcp.call_tool("new_drawing", {}))
    assert not result.isError
    assert result.structuredContent == {"result": "fixture-new"}
