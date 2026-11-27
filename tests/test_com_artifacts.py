"""Native file calls are fixtures here; real DWG validation is opt-in separately."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from autocad_mcp.cad.com_artifacts import (
    COMArtifacts,
    fingerprint,
    validated_directory,
    validated_filename,
)
from autocad_mcp.cad.connection import CADConnection
from autocad_mcp.config import Config


class Docs:
    def __init__(self, app, source):
        self.app = app
        self.items = [source]
        self.opens = 0

    @property
    def Count(self):
        return len(self.items)

    def Item(self, i):
        return self.items[i]

    def Open(self, path, readonly):
        self.opens += 1
        d = SimpleNamespace(
            Name=Path(path).name,
            FullName=path,
            ReadOnly=readonly,
            Saved=True,
            ModelSpace=[],
        )
        self.items.append(d)
        self.app.ActiveDocument = d
        return d


class InteropDocs:
    """Fixture whose Python map goes stale after Open but DISPIDs stay valid."""

    def __init__(self, underlying, count_faults=0):
        self.underlying = underlying
        self.count_faults = count_faults
        self.native_count_reads = 0
        self._oleobj_ = self

    def GetIDsOfNames(self, name):
        return {"Count": 1, "Item": 2, "Open": 3}[name]

    def Invoke(self, dispid, _lcid, _kind, _result, *args):
        if dispid == 1:
            self.native_count_reads += 1
            if self.underlying.opens and self.count_faults:
                self.count_faults -= 1
                raise AttributeError("<unknown>.Count")
            return len(self.underlying.items)
        if dispid == 2:
            return self.underlying.items[args[0]]
        if dispid == 3:
            return self.underlying.Open(*args)
        raise AssertionError("Unexpected fixture DISPID")

    @property
    def Count(self):
        if self.underlying.opens:
            raise AttributeError("<unknown>.Count")
        return len(self.underlying.items)

    def Item(self, index):
        if self.underlying.opens:
            raise AttributeError("<unknown>.Item")
        return self.underlying.items[index]


@pytest.fixture
def service():
    conn = CADConnection(Config(cad_type="AutoCAD", prog_id="fixture"))
    source = SimpleNamespace(
        Name="new.dwg", FullName="", ReadOnly=False, Saved=False, ModelSpace=[]
    )
    app = SimpleNamespace(ActiveDocument=source)
    app.Documents = Docs(app, source)
    conn.app = app
    conn.document = source
    conn.model_space = source.ModelSpace
    conn._owned_ids.add(conn.document_id(source))
    calls = []

    def save(path):
        calls.append(path)
        Path(path).write_bytes(b"AC1032-fixture-not-real-CAD")
        source.FullName = path
        source.Name = Path(path).name
        source.Saved = True

    source.SaveAs = save
    source.Activate = lambda: setattr(app, "ActiveDocument", source)
    return COMArtifacts(conn), calls


def test_save_copy_readonly_reopen_independent_identity_and_source_binding(
    service, tmp_path
):
    files, calls = service
    before = files.connection.binding()
    a = files.save_document_artifact(str(tmp_path), "example.dwg")
    assert len(calls) == 1 and a["source_document_id"] == before["document_id"]
    assert a["revision"] is None and a["verification"] == "not_performed"
    assert Path(a["path"]).parent.parent == tmp_path
    v = files.reopen_document_artifact(a["artifact_id"])
    assert (
        v["document_id"] != before["document_id"]
        and v["read_only"]
        and not v["managed"]
    )
    assert files.connection.binding()["document_id"] == before["document_id"]
    assert fingerprint(v["path"]) == fingerprint(a["path"])
    assert files.query_verification_entities(v["document_id"])["items"] == []


@pytest.mark.parametrize(
    "name", ["../bad.dwg", "CON.dwg", "NUL.any.dwg", "a/b.dwg", "a.dxf", "a:stream.dwg"]
)
def test_filename_rejection(name):
    with pytest.raises(ValueError):
        validated_filename(name)


def test_roots_bind_once_and_same_names_do_not_overwrite(service, tmp_path):
    files, calls = service
    a = files.save_document_artifact(str(tmp_path), "same.dwg")
    b = files.save_document_artifact(str(tmp_path), "same.dwg")
    assert a["path"] != b["path"] and Path(a["path"]).is_file()
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError, match="ALREADY_BOUND"):
        files.save_document_artifact(str(other), "same.dwg")
    assert len(calls) == 2


def test_tampered_source_is_rejected_before_open(service, tmp_path):
    files, _ = service
    a = files.save_document_artifact(str(tmp_path), "x.dwg")
    Path(a["path"]).write_bytes(b"AC1032-tampered")
    with pytest.raises(ValueError, match="TAMPERED"):
        files.reopen_document_artifact(a["artifact_id"])
    assert files.connection.app.Documents.opens == 0


@pytest.mark.parametrize("change", ["edited", "renamed", "closed", "file_tampered"])
def test_verification_query_fails_closed_on_changed_document(service, tmp_path, change):
    files, _ = service
    a = files.save_document_artifact(str(tmp_path), "x.dwg")
    v = files.reopen_document_artifact(a["artifact_id"])
    doc = files.verifications[v["document_id"]][0]
    if change == "edited":
        doc.Saved = False
    if change == "renamed":
        doc.FullName = "different.dwg"
    if change == "closed":
        files.connection.app.Documents.items.remove(doc)
    if change == "file_tampered":
        Path(v["path"]).write_bytes(b"AC1032-other")
    with pytest.raises(ValueError):
        files.query_verification_entities(v["document_id"])


def test_bad_save_header_after_ack_does_not_register_artifact(service, tmp_path):
    files, _ = service

    def bad(path):
        Path(path).write_bytes(b"not-a-dwg")
        files.connection.document.FullName = path

    files.connection.document.SaveAs = bad
    with pytest.raises(ValueError, match="header"):
        files.save_document_artifact(str(tmp_path), "bad.dwg")
    assert (
        not files.artifacts
        and files.progress["state"] == "native_acknowledged_unverified"
    )


def test_registry_loss_is_not_recovered_from_a_filename(service, tmp_path):
    files, _ = service
    a = files.save_document_artifact(str(tmp_path), "x.dwg")
    fresh = COMArtifacts(files.connection)
    with pytest.raises(ValueError, match="NOT_AVAILABLE"):
        fresh.reopen_document_artifact(a["artifact_id"])


def test_other_empty_untitled_document_refused_before_native_open(service, tmp_path):
    files, _ = service
    a = files.save_document_artifact(str(tmp_path), "x.dwg")
    other = SimpleNamespace(FullName="", ModelSpace=SimpleNamespace(Count=0))
    files.connection.app.Documents.items.append(other)
    with pytest.raises(ValueError, match="OTHER_EMPTY_DOCUMENT"):
        files.reopen_document_artifact(a["artifact_id"])
    assert files.connection.app.Documents.opens == 0


def test_real_mcp_file_result_and_journal_roundtrip(service, tmp_path, monkeypatch):
    import asyncio

    from mcp.shared.memory import create_connected_server_and_client_session

    from autocad_mcp import state
    from autocad_mcp.cad.backends.com_backend import COMBackend
    from autocad_mcp.server import mcp

    files, calls = service
    session = SimpleNamespace(
        connection=files.connection, files=files, close=lambda: None
    )
    backend = COMBackend(files.connection.config, session_factory=lambda _: session)
    binding = backend.document_binding()
    state.close_backend()
    monkeypatch.setattr(state, "create_backend", lambda _: backend)

    async def run():
        async with create_connected_server_and_client_session(mcp) as client:

            async def call(op, args, doc, rid):
                r = await client.call_tool(
                    "execute_observed_operation",
                    dict(
                        instance_id=backend.instance_id,
                        request_id=rid,
                        document_id=doc,
                        operation=op,
                        arguments=args,
                    ),
                )
                assert not r.isError, r.content
                return r.structuredContent

            saved = await call(
                "save_document_artifact",
                dict(output_directory=str(tmp_path), file_name="x.dwg"),
                binding["document_id"],
                "save",
            )
            artifact = saved["result"]
            assert saved["receipt"]["file_result"] == artifact
            reopened = await call(
                "reopen_document_artifact",
                dict(artifact_id=artifact["artifact_id"]),
                binding["document_id"],
                "reopen",
            )
            verification = reopened["result"]
            assert (
                reopened["receipt"]["result_document_id"] == verification["document_id"]
            )
            await call(
                "query_verification_entities",
                dict(document_id=verification["document_id"]),
                verification["document_id"],
                "query",
            )
            status = await client.call_tool(
                "get_execution_status",
                dict(instance_id=backend.instance_id, request_id="save"),
            )
            assert (
                status.structuredContent["file_result"]["artifact_id"]
                == artifact["artifact_id"]
            )
            again = await call(
                "save_document_artifact",
                dict(output_directory=str(tmp_path), file_name="x.dwg"),
                binding["document_id"],
                "save",
            )
            assert again["result"] is None and len(calls) == 1

    try:
        asyncio.run(run())
    finally:
        state.close_backend()
        backend.close()


@pytest.mark.parametrize("ack", [False, True])
def test_file_failure_keeps_progress_and_duplicate_never_replays(
    service, tmp_path, ack
):
    from autocad_mcp.cad.backends.com_backend import COMBackend

    files, calls = service

    def broken_save(path):
        calls.append(path)
        Path(path).write_bytes(b"invalid-header")
        files.connection.document.FullName = path
        if not ack:
            raise RuntimeError("response lost after file side effect")

    files.connection.document.SaveAs = broken_save
    session = SimpleNamespace(
        connection=files.connection, files=files, close=lambda: None
    )
    backend = COMBackend(files.connection.config, session_factory=lambda _: session)
    try:
        binding = backend.document_binding()
        args = dict(output_directory=str(tmp_path), file_name="bad.dwg")
        kwargs = dict(
            request_id="save-failure",
            instance_id=backend.instance_id,
            document_id=binding["document_id"],
        )
        result = backend.execute_evidenced("save_document_artifact", args, **kwargs)
        receipt = result["receipt"]
        assert result["result"] is None and receipt["status"] == "failed"
        assert receipt["stage"] == ("observation_failed" if ack else "result_unknown")
        assert receipt["native_acknowledged"] is ack
        assert receipt["file_progress"]["state"] == (
            "native_acknowledged_unverified" if ack else "prepared"
        )
        assert not files.artifacts and Path(calls[0]).is_file()
        duplicate = backend.execute_evidenced("save_document_artifact", args, **kwargs)
        assert duplicate["receipt"] == receipt and len(calls) == 1
    finally:
        backend.close()


def test_symlink_and_parent_traversal_rejected(tmp_path):
    with pytest.raises(ValueError):
        validated_directory(str(tmp_path / ".." / tmp_path.name))
    link = tmp_path / "link"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks require developer mode")
    with pytest.raises(ValueError):
        validated_directory(str(link))


def test_snapshot_uses_native_collection_dispids_after_python_map_goes_stale(service):
    files, _ = service
    conn = files.connection
    docs = conn.app.Documents
    wrapper = InteropDocs(docs)
    conn.app.Documents = wrapper
    docs.opens = 1  # Stale-map condition only; no native Open in this fixture.
    rows, ids = conn.document_snapshot()
    assert rows == [conn.document]
    assert ids == {conn.document_id(conn.document)}
    assert wrapper.native_count_reads == 1


def test_reopen_retries_only_native_count_reads_after_one_acknowledged_open(
    service, tmp_path, monkeypatch
):
    from autocad_mcp.cad import capture

    monkeypatch.setattr(capture.time, "sleep", lambda _: None)
    monkeypatch.setattr(capture.pythoncom, "PumpWaitingMessages", lambda: None)
    files, saves = service
    source = files.connection.document
    docs = files.connection.app.Documents
    wrapper = InteropDocs(docs, count_faults=1)
    files.connection.app.Documents = wrapper
    artifact = files.save_document_artifact(str(tmp_path), "one.dwg")
    result = files.reopen_document_artifact(artifact["artifact_id"])
    assert docs.opens == 1 and len(saves) == 1
    assert wrapper.count_faults == 0
    assert result["read_only"] and result["document_id"] != artifact["source_document_id"]
    assert files.connection.document is source
    assert files.connection.app.ActiveDocument is source


def test_reopen_count_read_exhaustion_keeps_ack_and_never_replays_open(
    service, tmp_path, monkeypatch
):
    from autocad_mcp.cad import capture
    from autocad_mcp.cad.backends.com_backend import COMBackend

    monkeypatch.setattr(capture.time, "sleep", lambda _: None)
    monkeypatch.setattr(capture.pythoncom, "PumpWaitingMessages", lambda: None)
    files, saves = service
    source = files.connection.document
    docs = files.connection.app.Documents
    files.connection.app.Documents = InteropDocs(docs, count_faults=100)
    artifact = files.save_document_artifact(str(tmp_path), "retained.dwg")
    session = SimpleNamespace(connection=files.connection, files=files, close=lambda: None)
    backend = COMBackend(files.connection.config, session_factory=lambda _: session)
    args = {"artifact_id": artifact["artifact_id"]}
    kwargs = dict(
        request_id="reopen-count-failure",
        instance_id=backend.instance_id,
        document_id=artifact["source_document_id"],
    )
    try:
        result = backend.execute_evidenced("reopen_document_artifact", args, **kwargs)
        receipt = result["receipt"]
        assert receipt["stage"] == "observation_failed"
        assert receipt["native_acknowledged"] is True
        assert receipt["native_actions"] == [{"name": "Open", "acknowledged": True}]
        assert files.progress["state"] == "native_acknowledged_unverified"
        assert Path(files.progress["path"]).is_file()
        assert not files.verifications and files.connection.document is source
        duplicate = backend.execute_evidenced("reopen_document_artifact", args, **kwargs)
        assert duplicate["receipt"] == receipt
        assert docs.opens == 1 and len(saves) == 1
    finally:
        backend.close()
