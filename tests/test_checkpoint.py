"""Fixture native geometry; these tests do not certify a real recovered DWG."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from autocad_mcp.cad import checkpoint as cp
from autocad_mcp.cad.backends.com_backend import COMBackend
from autocad_mcp.cad.com_artifacts import COMArtifacts
from autocad_mcp.cad.connection import CADConnection
from autocad_mcp.config import Config


class Space:
    Count = 1

    def Item(self, index):
        return SimpleNamespace(
            ObjectName="AcDbLine",
            ObjectID=987,
            Handle="AB",
            Layer="0",
            Color=256,
            Linetype="ByLayer",
            LinetypeScale=1.0,
            Lineweight=-1,
            Visible=True,
            StartPoint=(0.0, 0.0, 0.0),
            EndPoint=(1.0, 2.0, 0.0),
            Normal=(0.0, 0.0, 1.0),
            Thickness=0.0,
        )


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "require_dead", lambda pid: None)
    grants = tmp_path / "grants"
    grants.mkdir()
    monkeypatch.setenv("AUTOCAD_MCP_CHECKPOINT_GRANTS", str(grants))
    source = tmp_path / "source.dwg"
    source.write_bytes(b"AC1032-fixture-not-real-dwg")
    evidence = tmp_path / "ledger.jsonl"
    evidence.write_text('{"status":"confirmed"}\n')
    output = tmp_path / "out"
    output.mkdir()
    frozen = cp.snapshot(SimpleNamespace(ModelSpace=Space()))
    frozen["entities"][0]["object_id"] = "123"
    grant = dict(
        contract="autocad-checkpoint-grant/1",
        authorized_by="local-test-review",
        writer_pid=123,
        cad_pid=456,
        unresolved_requests=[],
        execution_evidence_path=str(evidence),
        reviewed_execution_evidence_sha256=hashlib.sha256(
            evidence.read_bytes()
        ).hexdigest(),
        old_instance_id="old-instance",
        old_document_id="old-document",
        source_path=str(source),
        source_root=str(tmp_path),
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        source_byte_size=source.stat().st_size,
        output_directory=str(output),
        snapshot=frozen,
        snapshot_sha256=cp.digest(frozen),
    )
    conn = CADConnection(Config(cad_type="AutoCAD", prog_id="fixture"))

    class Docs:
        def __init__(self):
            self.rows = []
            self.opens = 0

        @property
        def Count(self):
            return len(self.rows)

        def Item(self, i):
            return self.rows[i]

        def Open(self, path, readonly):
            self.opens += 1
            doc = SimpleNamespace(
                FullName=path,
                Name=Path(path).name,
                ReadOnly=readonly,
                Saved=True,
                ModelSpace=Space(),
            )
            self.rows.append(doc)
            conn.app.ActiveDocument = doc

    docs = Docs()
    conn.app = SimpleNamespace(
        Documents=docs, GetAcadState=lambda: SimpleNamespace(IsQuiescent=True)
    )
    files = COMArtifacts(conn)
    backend = COMBackend(
        conn.config,
        session_factory=lambda _: SimpleNamespace(
            connection=conn, files=files, close=lambda: None
        ),
    )

    def write():
        (grants / "test.json").write_text(json.dumps(grant), encoding="utf-8")

    def call(rid="fork"):
        write()
        return backend.execute_evidenced(
            "fork_checkpoint",
            dict(grant_id="test"),
            request_id=rid,
            instance_id=backend.instance_id,
        )

    yield SimpleNamespace(
        grant=grant,
        write=write,
        call=call,
        backend=backend,
        conn=conn,
        docs=docs,
        files=files,
        source=source,
        grants=grants,
    )
    backend.close()


def test_verified_fork_new_owner_mapping_receipt_and_no_replay(recovery):
    r = recovery
    before = r.source.read_bytes()
    response = r.call()
    receipt = response["receipt"]
    result = response["result"]
    assert receipt["status"] == "succeeded", receipt
    assert result["managed"] and not result["quality_accepted"]
    assert (
        result["instance_id"] != "old-instance"
        and result["document_id"] != "old-document"
    )
    assert result["mapping"] == [
        dict(handle="AB", old_object_id="123", new_object_id="987", type="AcDbLine")
    ]
    assert receipt["file_result"] == result and r.source.read_bytes() == before
    assert (
        r.backend.execution_status(r.backend.instance_id, "fork")["file_result"]
        == result
    )
    assert r.call()["receipt"] == receipt and r.docs.opens == 1
    exported = r.backend.execute_evidenced(
        "get_checkpoint_snapshot",
        {},
        request_id="freeze",
        instance_id=r.backend.instance_id,
        document_id=result["document_id"],
    )
    assert exported["receipt"]["status"] == "succeeded"
    assert exported["result"]["snapshot_sha256"] == cp.digest(
        exported["result"]["snapshot"]
    )
    assert exported["result"]["source"]["sha256"] == result["working"]["sha256"]
    assert r.call("different")["receipt"]["status"] == "failed" and r.docs.opens == 1


@pytest.mark.parametrize(
    "fault",
    [
        "source",
        "snapshot_hash",
        "snapshot_fields",
        "extra",
        "native_fields",
        "owner",
        "unknown",
        "evidence",
        "wrong_identity",
        "lost_ack",
        "link",
        "outside_root",
        "open_readonly",
    ],
)
def test_failures_preserve_evidence_and_never_grant_owner(recovery, monkeypatch, fault):
    r = recovery
    if fault == "source":
        r.source.write_bytes(b"AC1032-changed")
    if fault == "snapshot_hash":
        r.grant["snapshot_sha256"] = "0" * 64
    if fault == "snapshot_fields":
        del r.grant["snapshot"]["entities"][0]["fields"]["Normal"]
    if fault == "extra":
        other = copy.deepcopy(r.grant["snapshot"]["entities"][0])
        other.update(handle="FF", object_id="321")
        r.grant["snapshot"]["entities"].append(other)
    if fault == "native_fields":
        r.grant["snapshot"]["entities"][0]["fields"]["Thickness"] = 12.0
    if fault in {"snapshot_fields", "extra", "native_fields"}:
        r.grant["snapshot_sha256"] = cp.digest(r.grant["snapshot"])
    if fault == "owner":
        monkeypatch.setattr(
            cp,
            "require_dead",
            lambda _: (_ for _ in ()).throw(ValueError("OWNER_STILL_RUNNING")),
        )
    if fault == "unknown":
        r.grant["unresolved_requests"] = ["unresolved-write"]
    if fault == "evidence":
        r.grant["reviewed_execution_evidence_sha256"] = "0" * 64
    if fault == "outside_root":
        r.grant["source_root"] = str(r.grants)
    if fault == "link":
        r.grant["source_path"] = str(
            r.source.parent / ".." / r.source.parent.name / "source.dwg"
        )
    if fault in {"wrong_identity", "lost_ack", "open_readonly"}:
        original = r.docs.Open

        def broken(path, readonly):
            original(path, readonly)
            if fault == "lost_ack":
                raise RuntimeError("Open side effect then response lost")
            if fault == "wrong_identity":
                r.docs.rows[0].FullName = "different.dwg"
            if fault == "open_readonly":
                r.docs.rows[0].ReadOnly = True

        r.docs.Open = broken
    response = r.call()
    receipt = response["receipt"]
    assert receipt["status"] == "failed" and response["result"] is None
    assert not r.conn._owned_ids and r.conn.document is None
    assert r.source.exists()
    if fault in {"extra", "native_fields", "wrong_identity", "open_readonly"}:
        assert receipt["stage"] == "observation_failed" and r.docs.opens == 1
    if fault == "lost_ack":
        assert receipt["stage"] == "result_unknown"
    count = r.docs.opens
    assert r.call()["receipt"] == receipt and r.docs.opens == count


def test_ambiguous_handles_not_resolved_by_geometry(recovery):
    frozen = copy.deepcopy(recovery.grant["snapshot"])
    other = copy.deepcopy(frozen["entities"][0])
    other["object_id"] = "999"
    frozen["entities"].append(other)
    with pytest.raises(ValueError, match="AMBIGUOUS_HANDLE"):
        cp.match(frozen, frozen)


def test_legacy_partial_snapshot_is_not_upgraded(recovery):
    with pytest.raises(ValueError, match="CONTRACT"):
        cp.validate_snapshot(dict(entities=[dict(object_id=1, type="AcDbLine")]))


@pytest.mark.parametrize("change", ["nan", "type", "missing_handle", "duplicate_id"])
def test_malformed_freeze_refused(recovery, change):
    frozen = copy.deepcopy(recovery.grant["snapshot"])
    row = frozen["entities"][0]
    if change == "nan":
        row["fields"]["Thickness"] = float("nan")
    if change == "type":
        row["type"] = "AcDbHatch"
    if change == "missing_handle":
        del row["handle"]
    if change == "duplicate_id":
        other = copy.deepcopy(row)
        other["handle"] = "AC"
        frozen["entities"].append(other)
    with pytest.raises(ValueError):
        cp.validate_snapshot(frozen)


def test_source_lock_denies_writer(recovery):
    import pywintypes
    import win32con
    import win32file

    with cp.locked_read(recovery.source):
        with pytest.raises(pywintypes.error):
            win32file.CreateFile(
                str(recovery.source),
                win32con.GENERIC_WRITE,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                None,
                win32con.OPEN_EXISTING,
                0,
                None,
            )


def test_durable_claim_refuses_after_journal_loss(recovery):
    r = recovery
    assert r.call()["receipt"]["status"] == "succeeded"
    r.backend.close()
    r.docs.rows.clear()
    r.conn.document = r.conn.model_space = None
    files = COMArtifacts(r.conn)
    backend = COMBackend(
        r.conn.config,
        session_factory=lambda _: SimpleNamespace(
            connection=r.conn, files=files, close=lambda: None
        ),
    )
    try:
        result = backend.execute_evidenced(
            "fork_checkpoint",
            dict(grant_id="test"),
            request_id="new-process",
            instance_id=backend.instance_id,
        )
        assert "ALREADY_RESERVED" in result["receipt"]["error"]["message"]
        assert r.docs.opens == 1 and (r.grants / "test.claim").exists()
    finally:
        backend.close()


def test_actual_running_owner_is_rejected():
    import os

    from autocad_mcp.cad.checkpoint import require_dead

    with pytest.raises(ValueError, match="OWNER_STILL_RUNNING"):
        require_dead(os.getpid())


def test_postflight_failure_revokes_owned_and_invalidates_result(recovery, monkeypatch):
    original = recovery.conn.binding
    calls = []

    def binding():
        calls.append(1)
        if len(calls) == 2:
            raise ValueError("postflight binding unavailable")
        return original()

    monkeypatch.setattr(recovery.conn, "binding", binding)
    result = recovery.call()
    assert result["receipt"]["stage"] == "observation_failed"
    assert result["result"] is None and not recovery.conn._owned_ids
    assert not result["receipt"]["file_result"]["managed"]
    assert not result["receipt"]["file_result"]["binding_valid"]


def test_real_mcp_transport_fork_and_reconciliation(recovery, monkeypatch):
    import asyncio

    from mcp.shared.memory import create_connected_server_and_client_session

    from autocad_mcp import state
    from autocad_mcp.server import mcp

    r = recovery
    state.close_backend()
    monkeypatch.setattr(state, "create_backend", lambda _: r.backend)
    r.write()

    async def run():
        async with create_connected_server_and_client_session(mcp) as client:
            args = dict(
                operation="fork_checkpoint",
                arguments=dict(grant_id="test"),
                request_id="mcp-fork",
                instance_id=r.backend.instance_id,
            )
            response = await client.call_tool("execute_observed_operation", args)
            assert not response.isError, response.content
            result = response.structuredContent["result"]
            assert result["mapping_complete"] and result["managed"]
            status = await client.call_tool(
                "get_execution_status",
                dict(request_id="mcp-fork", instance_id=r.backend.instance_id),
            )
            assert status.structuredContent["file_result"] == result
            duplicate = await client.call_tool("execute_observed_operation", args)
            assert duplicate.structuredContent["result"] is None and r.docs.opens == 1

    try:
        asyncio.run(run())
    finally:
        state.close_backend()
