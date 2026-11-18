"""Interactive crash/restart qualification using HTTP only, preserving original CAD processes."""
import argparse
import json
import os
import re
from pathlib import Path
import secrets
import socket
import time
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import httpx
from autocad_mcp.config import load_config,HTTPConfig
from autocad_mcp.cad.backends.http_backend import HTTPBackend,BridgeRemoteError
from .common import Records
from .native import Traffic,wait_for
from scripts.verify_http_bridge import cad_processes

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    records=Records(args.output)
    records.json("plan.json",{"mode":"cad_restart","launch":"operator normal desktop, no COM Dispatch"})
    baseline=cad_processes()
    owned=[]
    bundle=Path(os.environ["APPDATA"])/"Autodesk/ApplicationPlugins/AutoCADMCPBridge.bundle/Contents/Windows"
    settings=bundle/"bridge-settings.json"
    previous=settings.read_bytes() if settings.exists() else None
    token=secrets.token_urlsafe(48)
    old_token=os.environ.get("AUTOCAD_BRIDGE_TOKEN")
    os.environ["AUTOCAD_BRIDGE_TOKEN"]=token
    with socket.socket() as probe:
        probe.bind(("127.0.0.1",0));port=probe.getsockname()[1]
    settings.write_text(json.dumps({"token":token,"port":port}),encoding="utf-8")
    config=load_config().model_copy(update={"backend":"http","http":HTTPConfig(base_url=f"http://127.0.0.1:{port}")})
    raw=httpx.Client(base_url=config.http.base_url,headers={"Authorization":"Bearer "+token},trust_env=False,timeout=2)
    h=None
    fresh=None
    result={"completed":False,"passed":False}
    def connect():
        traffic=Traffic()
        client=httpx.Client(base_url=config.http.base_url,transport=traffic,timeout=5,trust_env=False)
        return HTTPBackend(config,client=client),traffic
    def new_pid(prompt):
        print(prompt,flush=True)
        pid=int(input("Owned CAD PID: "))
        if pid in baseline or pid in owned or pid not in cad_processes():
            raise RuntimeError("PID is not a newly created CAD process")
        owned.append(pid)
        def ready():
            response=raw.get("/v1/health",timeout=.5)
            data=response.json()
            return data if response.status_code==200 and data["process_id"]==pid else None
        return pid,wait_for(ready,timeout=120)
    try:
        first,health=new_pid("Normally launch a NEW dedicated AutoCAD, NETLOAD the installed Bridge and run MCPBRIDGE_START.")
        h,traffic=connect()
        document=h.execute("new_document",{})
        documents=h.status()["documents"]
        if any(not re.fullmatch(r"Drawing\d+\.dwg",d["name"]) for d in documents):
            raise RuntimeError("Unexpected non-scratch document in the new instance; preserve it")
        print(f"Own scratch drawing: {document}. In ONLY PID {first}, start LINE and leave it awaiting a point.",flush=True)
        input("Press Enter after LINE is waiting: ")
        rid=uuid4().hex
        traffic.reset()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(h.execute,"draw_line",{"start":[0,0,0],"end":[10,0,0]},request_id=rid)
            def queued():
                response=raw.get("/v1/jobs/"+rid)
                if response.status_code!=200:
                    return None
                data=response.json()
                if data.get("status")=="succeeded":
                    raise RuntimeError("LINE was not blocking; do not claim a queued-write crash")
                return data if data.get("status")=="queued" else None
            state=wait_for(queued,timeout=10)
            records.add("restart",event="queued_before_process_death",status=state["status"],write_posts=traffic.posts)
            print(f"Verified queued write. Terminate ONLY owned CAD PID {first}, then press Enter.",flush=True)
            input()
            wait_for(lambda:first not in cad_processes(),timeout=20)
            try:
                pending.result(timeout=10)
                raise AssertionError("Lost process returned success")
            except BridgeRemoteError as exc:
                if exc.code!="OUTCOME_UNKNOWN" or traffic.posts!=1:
                    raise
                result["lost_process_outcome"]=exc.code
                result["write_posts"]=traffic.posts
        second,new_health=new_pid("Normally launch a replacement NEW dedicated AutoCAD, NETLOAD Bridge and run MCPBRIDGE_START.")
        if new_health["instance_id"]==health["instance_id"]:
            raise AssertionError("Instance identity survived process replacement")
        try:
            h.execute("query_entities",{})
            raise AssertionError("Old client silently rebound")
        except BridgeRemoteError as exc:
            if exc.code!="OUTCOME_UNKNOWN":
                raise
            result["stale_client_rejected"]=True
        missing=raw.get("/v1/jobs/"+rid)
        if missing.status_code!=404 or missing.json()["error"]["code"]!="JOB_NOT_FOUND":
            raise AssertionError("Unexpected journal persistence semantics")
        fresh,_=connect()
        rebound=fresh.execute("new_document",{})
        if any(not re.fullmatch(r"Drawing\d+\.dwg",d["name"]) for d in fresh.status()["documents"]):
            raise RuntimeError("Unexpected non-scratch document in replacement instance; preserve it")
        if fresh.execute("query_entities",{})!=[]:
            raise AssertionError("New drawing is not empty")
        fresh.execute("draw_circle",{"center":[4,5,0],"radius":3})
        entities=fresh.execute("query_entities",{})
        if len(entities)!=1 or entities[0]["center"]!=[4,5,0] or entities[0]["radius"]!=3:
            raise AssertionError("Explicit rebind did not restore correct geometry")
        result.update(recovery_verified=True,journal_lost_explicitly=True,
            original_processes_preserved=baseline<=cad_processes())
        print(f"Recovery verified in {rebound}. Terminate ONLY owned replacement PID {second}, then press Enter.",flush=True)
        input()
        wait_for(lambda:second not in cad_processes(),timeout=20)
        if not baseline<=cad_processes():
            raise AssertionError("Original CAD process disappeared")
        result.update(completed=True,passed=True,owned_processes_closed=True,
            case="cad_process_restart",baseline_process_count=len(baseline),owned_process_count=2,
            outcome="queued write result unknown; no replay; stale client rejected; explicit rebind works")
    except Exception as exc:
        result.update(error_type=type(exc).__name__,error_code=getattr(exc,"code",None))
        records.add("run_failure",error_type=type(exc).__name__,error_code=getattr(exc,"code",None))
        raise
    finally:
        if h:h.close()
        if fresh:fresh.close()
        raw.close()
        if previous is None:settings.unlink(missing_ok=True)
        else:settings.write_bytes(previous)
        if old_token is None:os.environ.pop("AUTOCAD_BRIDGE_TOKEN",None)
        else:os.environ["AUTOCAD_BRIDGE_TOKEN"]=old_token
        records.json("restart.json",result)
        records.json("cleanup.json",{"owned_processes_remaining":sorted(set(owned)&cad_processes()),
            "original_processes_preserved":baseline<=cad_processes()})
        records.json("qualification.json",result)

if __name__=="__main__":
    main()
