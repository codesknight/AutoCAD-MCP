"""Real HTTP faults against a PID-checked, dedicated NativeTests instance only."""
import argparse
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pythoncom

from autocad_mcp.cad.backends.http_backend import BridgeRemoteError, HTTPBackend
from autocad_mcp.cad.capture import method, prop
from autocad_mcp.cad.geometry import to_variant_point
from autocad_mcp.config import load_config
from benchmarks.native import Traffic
from scripts.native_test_target import Busy, application


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owned-pid",type=int,required=True)
    parser.add_argument("--bridge-dir",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    pythoncom.CoInitialize();app=application(args.owned_pid)
    settings=json.loads((args.bridge_dir/"bridge-settings.json").read_text(encoding="utf-8"))
    config=load_config().model_copy(update={"backend":"http"})
    os.environ[config.http.token_env]=settings["token"]
    assert config.http.base_url==f"http://127.0.0.1:{settings.get('port',8765)}"
    traffic=Traffic();client=httpx.Client(base_url=config.http.base_url,transport=traffic,trust_env=False,timeout=10)
    backend=HTTPBackend(config,client=client);report=dict(passed=False,process_id=args.owned_pid)
    evidence=[]
    def record(name,value):
        evidence.append(dict(case=name,evidence=value))
        (out/"cases.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    def fresh():return HTTPBackend(config)
    def terminal(request_id):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            value=backend.execution_status(backend._instance,request_id)
            if value.get("job",{}).get("status") not in {None,"queued","running"}:return value
            time.sleep(.1)
        raise TimeoutError("Job did not become terminal")
    try:
        assert backend._request("GET","/v1/health")["process_id"]==args.owned_pid
        backend.execute("new_document",{})
        doc=prop(app,"ActiveDocument");target=backend._document;instance=backend._instance
        assert prop(doc,"Name")==next(d["name"] for d in backend.status()["documents"] if d["document_id"]==target)
        rid=uuid4().hex;traffic.reset();traffic.drop_post=True
        try:
            backend.execute("draw_line",dict(start=[0,0,0],end=[10,0,0]),request_id=rid)
            raise AssertionError("Dropped response was accepted as success")
        except BridgeRemoteError as error:
            assert error.outcome=="outcome_unknown" and traffic.posts==1
        committed=terminal(rid)
        assert committed["job"]["status"]=="succeeded"
        assert committed["operation"]=="draw_line" and committed["request_document_id"]==target
        assert len(backend.execute("query_entities",{}))==1
        record("real_post_response_loss_no_replay",dict(write_posts=1,record=committed))
        # Corrupt actual read responses at the transport boundary, never CAD data.
        class CorruptRead(httpx.BaseTransport):
            def __init__(self,fault):self.inner=httpx.HTTPTransport(retries=0);self.fault=fault;self.posts=0
            def handle_request(self,request):
                self.posts+=int(request.method=="POST")
                response=self.inner.handle_request(request);response.read()
                if "/v1/requests/" not in request.url.path:return response
                data=response.json();response.close()
                if self.fault=="request_id":data["job"]["request_id"]="foreign-request"
                if self.fault=="document_id":data["job"]["document_id"]="foreign-document"
                if self.fault=="instance_id":data["job"]["instance_id"]="foreign-instance"
                if self.fault=="missing_identity":data.pop("operation")
                return httpx.Response(200,json=data,request=request)
            def close(self):self.inner.close()
        for fault in ["request_id","document_id","instance_id","missing_identity"]:
            corrupt=CorruptRead(fault)
            cold=HTTPBackend(config,client=httpx.Client(base_url=config.http.base_url,transport=corrupt,trust_env=False))
            try:
                rejected=cold.execution_status(instance,rid)
                assert rejected["status"]=="unresolved" and rejected["replay_safe"] is False and corrupt.posts==0
                record("tampered_real_record_"+fault,dict(injection="transport_read_response_only",lookup=rejected,write_posts=0))
            finally:cold.close()
        assert backend.execution_status(instance,rid)==committed
        with Busy(args.owned_pid):
            # No /status call is needed by a completely fresh reconciliation client.
            cold=fresh()
            try:
                recovered=cold.execution_status(instance,rid)
                assert recovered["job"]["status"]=="succeeded"
                record("acknowledged_write_reconciled_while_native_main_thread_blocked",recovered)
            finally:cold.close()
            pending_id=uuid4().hex;traffic.reset();backend._config.request_timeout_seconds=.25
            try:
                backend.execute("draw_line",dict(start=[20,0,0],end=[30,0,0]),request_id=pending_id)
                raise AssertionError("Pending write falsely confirmed")
            except BridgeRemoteError as error:assert error.outcome=="outcome_unknown" and traffic.posts==1
            pending=backend.execution_status(instance,pending_id)
            assert pending["job"]["status"]=="queued"
            record("native_busy_pending_without_replay",dict(write_posts=1,record=pending))
        backend._config.request_timeout_seconds=30
        finished=terminal(pending_id)
        assert finished["job"]["status"]=="succeeded" and len(backend.execute("query_entities",{}))==2
        record("delayed_completion_readonly_reconciliation",finished)
        # An external native edit must invalidate a previous database revision.
        revision=next(d["revision"] for d in backend.status()["documents"] if d["document_id"]==target)
        method(prop(doc,"ModelSpace"),"AddLine")(to_variant_point(40,0,0),to_variant_point(50,0,0))
        try:
            backend.execute("draw_line",dict(start=[60,0,0],end=[70,0,0]),expected_revision=revision)
            raise AssertionError("Stale revision accepted after external edit")
        except BridgeRemoteError as error:assert error.code=="REVISION_CONFLICT" and error.outcome=="not_executed"
        assert len(backend.execute("query_entities",{}))==3
        record("external_native_edit_revision_guard",dict(previous_revision=revision,entities=3))
        missing=backend.execution_status(instance,uuid4().hex)
        assert missing["status"]=="unresolved" and missing["replay_safe"] is False
        record("missing_record_not_safe_to_replay",missing)
        # Restart only this dedicated fixture's Bridge; old journal is not persisted.
        method(doc,"SendCommand")("MCPBRIDGE_STOP\n")
        time.sleep(.3)
        method(doc,"SendCommand")("MCPBRIDGE_START\n")
        deadline=time.monotonic()+15
        while True:
            cold=fresh()
            try:
                changed=cold.execution_status(instance,rid)
                if changed.get("instance_id")!=instance:break
            except BridgeRemoteError:
                pass
            finally:cold.close()
            if time.monotonic()>deadline:raise TimeoutError("New Bridge instance not observed")
            time.sleep(.2)
        cold=fresh()
        try:
            assert changed["status"]=="unresolved" and changed["reason"]=="INSTANCE_MISMATCH"
            same_request_new_instance=cold.execution_status(changed["instance_id"],rid)
            assert same_request_new_instance["status"]=="unresolved"
            record("bridge_restart_journal_loss",dict(old_instance=instance,new_lookup=changed,missing=same_request_new_instance))
        finally:cold.close()
        report["passed"]=True
    except Exception as error:
        report["error"]=dict(type=type(error).__name__,message=str(error));raise
    finally:
        backend.close()
        (out/"qualification.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))


if __name__=="__main__":main()
