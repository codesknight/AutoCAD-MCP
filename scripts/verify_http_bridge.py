"""Verify against an already-open AutoCAD; close only drawings created here."""
import argparse
import asyncio
import csv
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from autocad_mcp.config import HTTPConfig, load_config
from autocad_mcp.cad.backends.http_backend import HTTPBackend, BridgeRemoteError

ROOT = Path(__file__).resolve().parents[1]

def cad_processes():
    output = subprocess.check_output(
        ["tasklist","/FI","IMAGENAME eq acad.exe","/FO","CSV","/NH"], text=True)
    return {int(row[1]) for row in csv.reader(output.splitlines())
            if len(row) > 1 and row[0].lower() == "acad.exe"}


def cad_read(callback, timeout=15):
    """Retry read-only COM queries while a newly opened drawing initializes."""
    import pythoncom
    deadline = time.monotonic()+timeout
    while True:
        try:
            return callback()
        except (AttributeError, pythoncom.com_error):
            if time.monotonic() >= deadline:
                raise RuntimeError("AutoCAD did not finish initializing its document") from None
            time.sleep(0.2)


def backend_config(url):
    return load_config().model_copy(update={
        "backend":"http", "http":HTTPConfig(base_url=str(url).rstrip("/"))})


async def verify_client(client, owned_documents):
    await client.initialize()
    assert len((await client.list_tools()).tools) == 40
    async def call(name, args):
        response = await client.call_tool(name, args)
        assert not response.isError, response.content
        return response.structuredContent["result"]
    document = await call("new_drawing", {})
    owned_documents.add(document)
    await call("draw_circle", {"center_x":4,"center_y":5,"center_z":0,"radius":3})
    rows = json.loads(await call("query_entities", {}))
    assert len(rows) == 1 and rows[0]["center"] == [4,5,0] and rows[0]["radius"] == 3
    unsupported = await client.call_tool("draw_text", {
        "position_x":0,"position_y":0,"position_z":0,"text":"unsupported","height":2})
    assert unsupported.isError
    return {"document":document,"entity_count":1,"unsupported_operation_rejected":True}


async def verify_mcp(env, owned_documents):
    parameters = StdioServerParameters(command=sys.executable,
        args=["-m", "autocad_mcp.server"], cwd=str(ROOT), env=env)
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as client:
            return await verify_client(client, owned_documents)


def verify_mcp_http(env, temporary, owned_documents):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1",0))
        port = probe.getsockname()[1]
    code = ("from autocad_mcp.server import mcp; "
            f"mcp.settings.port={port}; mcp.run(transport='streamable-http')")
    with (temporary/"mcp-http.log").open("w", encoding="utf-8") as log:
        server = subprocess.Popen([sys.executable,"-c",code],env=env,cwd=ROOT,
                                  stdout=log,stderr=log)
        try:
            deadline = time.monotonic() + 20
            while True:
                try:
                    with socket.create_connection(("127.0.0.1",port),timeout=0.5):
                        break
                except OSError:
                    if server.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("Owned MCP HTTP server did not start")
                    time.sleep(0.1)
            async def run():
                async with httpx.AsyncClient(trust_env=False) as http_client:
                    async with streamable_http_client(f"http://127.0.0.1:{port}/mcp",
                                                      http_client=http_client) as (read,write,_):
                        async with ClientSession(read,write) as client:
                            return await verify_client(client, owned_documents)
            return asyncio.run(run())
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


def verify(backend, client, owned_documents):
    try:
        backend.execute("draw_line", {"start":[0,0,0],"end":[1,0,0]})
        raise AssertionError("Unmanaged document accepted a write")
    except BridgeRemoteError as exc:
        assert exc.code == "FORBIDDEN", str(exc)
    document = backend.execute("new_document", {})
    owned_documents.add(document)
    backend.execute("create_layer", {"name":"HTTP_SMOKE","color":1})
    request_id = uuid4().hex
    line_args = {"start":[0,0,0],"end":[10,0,0],"layer":"HTTP_SMOKE"}
    line = backend.execute("draw_line", line_args, request_id=request_id)
    assert backend.execute("draw_line", line_args, request_id=request_id) == line
    try:
        backend.execute("draw_line", {"start":[0,0,0],"end":[11,0,0]}, request_id=request_id)
        raise AssertionError("Conflicting request ID accepted")
    except BridgeRemoteError as exc:
        assert exc.code == "REQUEST_ID_CONFLICT", str(exc)
    circle = backend.execute("draw_circle", {"center":[20,0,0],"radius":5,"layer":"HTTP_SMOKE"})
    assert backend.execute("get_entity", {"object_id":line})["end_point"] == [10,0,0]
    assert backend.execute("get_entity", {"object_id":circle})["radius"] == 5
    before = backend.execute("query_entities", {})
    assert len(before) == 2
    try:
        backend.execute_batch([
            {"id":"layer","operation":"create_layer","args":{"name":"MUST_ROLL_BACK"}},
            {"id":"line","operation":"draw_line","args":{"start":[1,1,0],"end":[2,2,0],"layer":"MUST_ROLL_BACK"}},
            {"id":"fail","operation":"draw_circle","args":{"center":[0,0,0],"radius":-1}},
        ])
        raise AssertionError("Invalid batch succeeded")
    except BridgeRemoteError as exc:
        assert exc.code == "INVALID_ARGUMENT" and exc.outcome == "rolled_back", str(exc)
    assert backend.execute("query_entities", {}) == before
    assert "MUST_ROLL_BACK" not in backend.execute("list_layers", {})
    result = backend.execute_batch([
        {"id":"layer","operation":"create_layer","args":{"name":"BATCH_OK"}},
        {"id":"line","operation":"draw_line","args":{"start":[1,1,0],"end":[2,2,0],"layer":"BATCH_OK"}},
    ])
    assert len(result) == 2 and len(backend.execute("query_entities", {})) == 3
    status = backend.status()
    current = next(row for row in status["documents"] if row["name"] == document)
    try:
        backend.execute("draw_circle", {"center":[0,0,0],"radius":1},
                        expected_revision=current["revision"]-1)
        raise AssertionError("Stale revision accepted")
    except BridgeRemoteError as exc:
        assert exc.code == "REVISION_CONFLICT", str(exc)
    wrong = client.post("/v1/execute", json={"request_id":uuid4().hex,
        "document_id":"not-a-session","operation":"draw_line","args":line_args}).json()
    for _ in range(100):
        if wrong["status"] not in {"queued","running"}:
            break
        time.sleep(0.05)
        wrong = client.get("/v1/jobs/"+wrong["request_id"]).json()
    assert wrong["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert client.get("/v1/health", headers={"Authorization":"Bearer invalid"}).status_code == 401
    assert client.get("/v1/health", headers={"Origin":"http://example.test"}).status_code == 403
    other = HTTPBackend(backend_config(client.base_url))
    try:
        owned_documents.add(other.execute("new_document", {}))
        backend.execute("draw_line", {"start":[30,0,0],"end":[40,0,0]})
        assert len(backend.execute("query_entities", {})) == 4
        assert other.execute("query_entities", {}) == []
    finally:
        other.close()
    return dict(document=document,entity_count=4,deduplication=True,request_conflict=True,
        atomic_rollback=True,atomic_commit=True,revision_conflict=True,wrong_document_rejected=True,
        document_binding=True,authentication=True,origin_rejected=True,unmanaged_write_rejected=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT/".git/http-bridge-verification.json")
    args = parser.parse_args()
    existing_pids = cad_processes()
    if len(existing_pids) != 1:
        raise RuntimeError("Start exactly one AutoCAD normally before running this attach-only test; no CAD process is auto-launched")
    bundle = Path(os.environ["APPDATA"])/"Autodesk/ApplicationPlugins/AutoCADMCPBridge.bundle/Contents/Windows/AutoCADBridge.dll"
    if not bundle.is_file():
        raise RuntimeError("Build and install the Bridge first")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1",0))
        port = probe.getsockname()[1]
    token = secrets.token_urlsafe(48)
    env = os.environ.copy()
    env.update(AUTOCAD_BRIDGE_TOKEN=token,AUTOCAD_BRIDGE_PORT=str(port))
    os.environ["AUTOCAD_BRIDGE_TOKEN"] = token
    report = {"sdk":"8.0.428","target":"net8.0-windows","protocol":"1",
              "launch_method":"attach_existing", "completed":False}
    report["tested_dll_sha256"] = hashlib.sha256(bundle.read_bytes()).hexdigest()
    report["base_git_sha"] = subprocess.check_output(
        ["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    owned_documents = set()
    closed_documents = []
    with tempfile.TemporaryDirectory(prefix="bridge-smoke-",dir=ROOT/".git") as temporary:
        temp = Path(temporary)
        url = f"http://127.0.0.1:{port}"
        cfg = backend_config(url)
        config_path = temp/"http-config.json"
        config_path.write_text(cfg.model_dump_json(),encoding="utf-8")
        env["AUTOCAD_MCP_CONFIG"] = str(config_path)
        settings_path = bundle.parent/"bridge-settings.json"
        previous_settings = settings_path.read_bytes() if settings_path.exists() else None
        settings_path.write_text(json.dumps({"token":token,"port":port}),encoding="utf-8")
        backend = None
        cad_app = None
        original_document = None
        try:
            import win32com.client
            import win32process
            cad_app = win32com.client.GetActiveObject(cfg.prog_id)
            pid = win32process.GetWindowThreadProcessId(cad_app.HWND)[1]
            assert pid in existing_pids, "Unexpected COM target"
            report["existing_pid"] = pid
            if cad_read(lambda: cad_app.Documents.Count):
                original_document = cad_read(lambda: cad_app.ActiveDocument.Name)
            else:
                cad_app.Documents.Add()
                owned_documents.add(cad_read(lambda: cad_app.ActiveDocument.Name))
            cad_read(lambda: cad_app.ActiveDocument.ModelSpace.Count)
            cad_app.ActiveDocument.SendCommand(
                '(command "_NETLOAD" "'+bundle.as_posix()+'")\nMCPBRIDGE_START\n')
            print(f"Attached to existing AutoCAD PID {pid}; native plugin bootstrap submitted",flush=True)
            with httpx.Client(base_url=url,headers={"Authorization":"Bearer "+token},
                              trust_env=False,timeout=5) as client:
                deadline = time.monotonic()+20
                while time.monotonic() < deadline:
                    try:
                        health = client.get("/v1/health",timeout=0.5)
                        if health.status_code == 200:
                            break
                    except httpx.RequestError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError("Bridge did not start; inspect local AutoCAD-MCP bridge.log")
                report["health"] = health.json()
                assert report["health"]["process_id"] == pid
                backend = HTTPBackend(cfg)
                report["cad"] = verify(backend,client,owned_documents)
                print("Native CAD transactions and safety checks passed",flush=True)
                report["mcp_stdio"] = asyncio.run(verify_mcp(env,owned_documents))
                report["mcp_streamable_http"] = verify_mcp_http(env,temp,owned_documents)
                report["completed"] = True
        finally:
            if backend is not None:
                backend.close()
            if cad_app is not None:
                try:
                    if cad_app.Documents.Count:
                        cad_app.ActiveDocument.SendCommand("MCPBRIDGE_STOP\n")
                except Exception:
                    pass
                for _ in range(len(owned_documents)+3):
                    try:
                        candidates = [doc for doc in cad_app.Documents
                                      if doc.Name in owned_documents and not doc.FullName]
                        if not candidates:
                            break
                        doc = candidates[-1]
                        name = doc.Name
                        doc.Close(False)
                        closed_documents.append(name)
                    except AttributeError:
                        time.sleep(0.2)
                    except Exception:
                        break
                if original_document is not None:
                    try:
                        for doc in cad_app.Documents:
                            if doc.Name == original_document:
                                cad_app.ActiveDocument = doc
                                break
                    except Exception:
                        pass
            if previous_settings is None:
                settings_path.unlink(missing_ok=True)
            else:
                settings_path.write_bytes(previous_settings)
            report["closed_test_documents"] = closed_documents
            report["test_documents_remaining"] = sorted(owned_documents-set(closed_documents))
            report["existing_process_preserved"] = existing_pids <= cad_processes()
            with httpx.Client(trust_env=False,timeout=0.5) as probe:
                report["bridge_listener_stopped"] = False
                deadline = time.monotonic()+8
                while time.monotonic() < deadline:
                    try:
                        probe.get(url+"/v1/health",headers={"Authorization":"Bearer "+token})
                        time.sleep(0.1)
                    except httpx.RequestError:
                        report["bridge_listener_stopped"] = True
                        break
            report["completed"] = report["completed"] and not report["test_documents_remaining"] and report["bridge_listener_stopped"]
            args.report.parent.mkdir(parents=True,exist_ok=True)
            args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
            print(f"Closed test drawings and preserved existing CAD; report: {args.report}",flush=True)
    assert report["completed"], "Validation or cleanup did not complete; inspect the report"
    print("HTTP Bridge validation completed for stdio and Streamable HTTP",flush=True)


if __name__ == "__main__":
    main()
