"""Attach-only native harness. All CAD writes are confined to owned scratch documents."""
import gc
import hashlib
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
from uuid import uuid4

import httpx
from autocad_mcp.config import HTTPConfig, load_config
from autocad_mcp.cad.backends.http_backend import HTTPBackend
from scripts.verify_http_bridge import cad_processes, cad_read

def wait_for(callback, timeout=30, interval=.1):
    deadline=time.monotonic()+timeout
    last=None
    while time.monotonic()<deadline:
        try:
            value=callback()
            if value:
                return value
        except (AttributeError, httpx.RequestError) as exc:
            last=type(exc).__name__
        time.sleep(interval)
    raise TimeoutError(f"Condition did not complete ({last})")

def memory(pid):
    import win32api
    import win32process
    handle=win32api.OpenProcess(0x410,False,pid)
    try:
        info=win32process.GetProcessMemoryInfo(handle)
    finally:
        handle.Close()
    return {"working_set_bytes":info["WorkingSetSize"],
            "private_bytes":info.get("PrivateUsage",info["PagefileUsage"])}

class Traffic(httpx.BaseTransport):
    def __init__(self):
        self.inner=httpx.HTTPTransport(retries=0)
        self.drop_post=False
        self.drop_poll=False
        self.reset()
    def reset(self):
        self.requests=0
        self.posts=0
        self.response_bytes=0
        self.metrics={}
    def handle_request(self, request):
        self.requests+=1
        self.posts+=int(request.method=="POST")
        if self.drop_poll and request.method=="GET" and "/v1/jobs/" in request.url.path:
            self.drop_poll=False
            raise httpx.ReadTimeout("Injected poll disconnect",request=request)
        response=self.inner.handle_request(request)
        response.read()
        self.response_bytes+=len(response.content)
        try:
            data=response.json()
            if data.get("metrics"):
                self.metrics[data["request_id"]]=data["metrics"]
        except ValueError:
            pass
        if self.drop_post and request.method=="POST":
            self.drop_post=False
            response.close()
            raise httpx.ReadTimeout("Injected response loss after real acceptance",request=request)
        return response
    def close(self):
        self.inner.close()
    def snapshot(self):
        return dict(http_requests=self.requests,http_posts=self.posts,http_response_bytes=self.response_bytes,
            bridge_execution_ms=sum(m["execution_ms"] for m in self.metrics.values()),
            bridge_queue_ms=sum(m["queue_ms"] for m in self.metrics.values()))

class Native:
    def __init__(self, records, owned_pid=None, preserve_existing=False):
        import pythoncom
        import win32com.client
        import win32process
        self.records=records
        self.config=load_config()
        if self.config.backend!="com":
            raise RuntimeError("Run with the repository default COM config; do not change the default for qualification")
        self.pids=cad_processes()
        if len(self.pids)!=1:
            raise RuntimeError("Normally launch exactly one dedicated, empty AutoCAD before running; no automatic Dispatch launch")
        self.pid=next(iter(self.pids))
        if owned_pid is not None and self.pid!=owned_pid:
            raise RuntimeError("Owned PID does not match the only AutoCAD process")
        self.owned_pid=owned_pid
        pythoncom.CoInitialize()
        self.app=win32com.client.GetActiveObject(self.config.prog_id)
        if cad_read(lambda:win32process.GetWindowThreadProcessId(self.app.HWND)[1])!=self.pid:
            raise RuntimeError("Unexpected COM target")
        self.original_names=cad_read(lambda:[d.Name for d in self.app.Documents])
        self.original_active=cad_read(lambda:self.app.ActiveDocument.Name) if self.original_names else None
        if self.original_names and not preserve_existing:
            raise RuntimeError("Qualification requires an empty dedicated instance, with no user drawings open")
        self.owned=set()
        self.original_settings=None
        self.settings_written=False
        self.running=False
        self.bundle=Path(os.environ["APPDATA"])/"Autodesk/ApplicationPlugins/AutoCADMCPBridge.bundle/Contents/Windows/AutoCADBridge.dll"
        if not self.bundle.exists():
            raise RuntimeError("Install the Bridge first")
        self.settings=self.bundle.parent/"bridge-settings.json"
        self.original_settings=self.settings.read_bytes() if self.settings.exists() else None
        self.token=secrets.token_urlsafe(48)
        self.old_token=os.environ.get("AUTOCAD_BRIDGE_TOKEN")
        os.environ["AUTOCAD_BRIDGE_TOKEN"]=self.token
        with socket.socket() as probe:
            probe.bind(("127.0.0.1",0))
            self.port=probe.getsockname()[1]
        self.url=f"http://127.0.0.1:{self.port}"
        self.http_config=self.config.model_copy(update={"backend":"http","http":HTTPConfig(base_url=self.url)})
        self.raw=httpx.Client(base_url=self.url,headers={"Authorization":"Bearer "+self.token},trust_env=False,timeout=5)
        self.app.Documents.Add("acadiso.dwt")
        self.bootstrap=cad_read(lambda:self.app.ActiveDocument.Name)
        self.owned.add(self.bootstrap)
        self.settings.write_text(json.dumps({"token":self.token,"port":self.port}),encoding="utf-8")
        self.settings_written=True
        self.command('(command "_NETLOAD" "'+self.bundle.as_posix()+'")\nMCPBRIDGE_STOP\nMCPBRIDGE_START\n')
        print("NETLOAD submitted. If AutoCAD asks, manually choose Load Once; security settings are unchanged.",flush=True)
        self.start(wait=600,submitted=True)
    def command(self, text):
        # The script targets only its own instance and drawing; never arbitrary remote input.
        cad_read(lambda:self.app.ActiveDocument).SendCommand(text)
    def start(self, wait=30, submitted=False):
        try:
            response=self.raw.get("/v1/health",timeout=.5)
            ready=response.status_code==200
        except httpx.RequestError:
            ready=False
        if not ready and not submitted:
            self.command("MCPBRIDGE_START\n")
        def health():
            r=self.raw.get("/v1/health",timeout=.5)
            return r.json() if r.status_code==200 else None
        state=wait_for(health,timeout=wait)
        if state["process_id"]!=self.pid:
            raise RuntimeError("Unexpected Bridge owner")
        self.instance=state["instance_id"]
        self.running=True
    def stop(self):
        self.command("MCPBRIDGE_STOP\n")
        def stopped():
            try:
                self.raw.get("/v1/health",timeout=.2)
                return False
            except httpx.ConnectError:
                return True
        wait_for(stopped,timeout=15)
        self.running=False
    def restart(self):
        self.stop()
        old=self.instance
        self.start()
        if self.instance==old:
            raise RuntimeError("Bridge instance ID did not change")
    def backend(self, timeout=30):
        traffic=Traffic()
        cfg=self.http_config.model_copy(update={"http":self.http_config.http.model_copy(update={"request_timeout_seconds":timeout})})
        client=httpx.Client(base_url=self.url,transport=traffic,timeout=httpx.Timeout(timeout,connect=3),trust_env=False)
        return HTTPBackend(cfg,client=client),traffic
    def new_document(self, backend):
        request_id=uuid4().hex
        name=backend.execute("new_document",{},request_id=request_id)
        self.owned.add(name)
        doc=cad_read(lambda:self.app.Documents.Item(name))
        if cad_read(lambda:doc.ModelSpace.Count):
            raise RuntimeError("Fixture document is not blank")
        doc.SetVariable("INSUNITS",4)
        doc.SetVariable("GRIDMODE",0)
        job=backend.get_job(request_id)
        print(f"Scratch target: {name}",flush=True)
        return name,job.document_id
    def activate(self, name):
        if name not in self.owned:
            raise RuntimeError("Refusing to activate an unowned document")
        self.app.ActiveDocument=cad_read(lambda:self.app.Documents.Item(name))
    def close_document(self, name):
        if name not in self.owned:
            raise RuntimeError("Refusing to close an unowned document")
        names=cad_read(lambda:[d.Name for d in self.app.Documents])
        if name in names:
            cad_read(lambda:self.app.Documents.Item(name)).Close(False)
            wait_for(lambda:name not in cad_read(lambda:[d.Name for d in self.app.Documents]))
        self.owned.discard(name)
    def poll(self, rid, timeout=30):
        def terminal():
            data=self.raw.get("/v1/jobs/"+rid).json()
            return data if data.get("status") not in ("queued","running") else None
        return wait_for(terminal,timeout)
    def busy(self):
        self.command("_.LINE\n")
        wait_for(lambda:bool(cad_read(lambda:self.app.ActiveDocument.GetVariable("CMDACTIVE"),timeout=2)),timeout=5)
    def idle(self):
        if not cad_read(lambda:self.app.ActiveDocument.GetVariable("CMDACTIVE"),timeout=2):
            return
        self.command("\x03\x03")
        wait_for(lambda:not cad_read(lambda:self.app.ActiveDocument.GetVariable("CMDACTIVE"),timeout=2),timeout=10)
    def environment(self):
        def git(*args):
            return subprocess.check_output(["git",*args],text=True).strip()
        import platform
        import win32api
        import win32process
        handle=win32api.OpenProcess(0x410,False,self.pid)
        try:
            version=win32api.GetFileVersionInfo(win32process.GetModuleFileNameEx(handle,0),"\\")
            parts=[version["FileVersionMS"]>>16,version["FileVersionMS"]&65535,
                   version["FileVersionLS"]>>16,version["FileVersionLS"]&65535]
        finally:
            handle.Close()
        hardware=json.loads(subprocess.check_output(["powershell","-NoProfile","-Command",
            "@{cpu=(Get-CimInstance Win32_Processor).Name;ram_bytes=(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory}|ConvertTo-Json -Compress"],
            text=True,creationflags=subprocess.CREATE_NO_WINDOW))
        return dict(recorded_date=datetime.now(timezone(timedelta(hours=8))).date().isoformat(),
            timezone="Asia/Shanghai",git_sha=git("rev-parse","HEAD"),
            tracked_diff=git("diff","--name-only").splitlines(),python_version=os.sys.version.split()[0],
            sdk=subprocess.check_output([str(Path.home()/".dotnet/dotnet.exe"),"--version"],text=True).strip(),
            cad_version=cad_read(lambda:self.app.Version),cad_file_version=".".join(map(str,parts)),
            os_version=platform.platform(),hardware=hardware,
            harness_sha256={p.as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in Path("benchmarks").glob("*.py")},
            bridge_sha256=hashlib.sha256(self.bundle.read_bytes()).hexdigest(),
            bridge_source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path("plugin/AutoCADBridge").glob("*.cs")},
            logical_cpus=os.cpu_count(),backend_default=self.config.backend,launch="normal_desktop_then_attach",
            fixture="fresh Bridge-created acadiso.dwt document; INSUNITS=4; no save; no explicit timed regen",
            units="millimetres",numeric_tolerance=1e-8,query_limit=1000,batch_limit=200,
            journal_capacity=2048,journal_ttl_seconds=600,poll_interval_seconds=.05,
            existing_documents_preserved=len(self.original_names),pid=self.pid,memory_start=memory(self.pid))
    def close(self):
        report={"closed_documents":[],"remaining_documents":[],"listener_stopped":False,"cad_process_closed":False}
        try:
            candidates=self.owned & set(cad_read(lambda:[d.Name for d in self.app.Documents]))
            if candidates:
                # Never cancel an interactive command in an original/user document.
                self.activate(sorted(candidates)[0])
                try:
                    self.idle()
                except Exception as exc:
                    report["idle_error"]=type(exc).__name__
                try:
                    self.stop()
                    report["listener_stopped"]=True
                except Exception as exc:
                    report["listener_error"]=type(exc).__name__
            elif not self.running:
                report["listener_stopped"]=True
            for name in sorted(self.owned,reverse=True):
                try:
                    self.close_document(name)
                    report["closed_documents"].append(name)
                except Exception as exc:
                    report["remaining_documents"].append(name)
            if self.original_active and self.original_active in cad_read(lambda:[d.Name for d in self.app.Documents]):
                self.app.ActiveDocument=cad_read(lambda:self.app.Documents.Item(self.original_active))
                report["original_active_restored"]=True
            if not report["remaining_documents"] and not self.original_names and self.owned_pid==self.pid:
                self.app.Quit()
                self.app=None
                gc.collect()
                wait_for(lambda:self.pid not in cad_processes(),timeout=20)
                report["cad_process_closed"]=True
        finally:
            if self.settings_written:
                if self.original_settings is None:
                    self.settings.unlink(missing_ok=True)
                else:
                    self.settings.write_bytes(self.original_settings)
            self.raw.close()
            if self.old_token is None:
                os.environ.pop("AUTOCAD_BRIDGE_TOKEN",None)
            else:
                os.environ["AUTOCAD_BRIDGE_TOKEN"]=self.old_token
            import pythoncom
            pythoncom.CoUninitialize()
            self.records.json("cleanup.json",report)
        return report
