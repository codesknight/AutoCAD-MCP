"""Native fault matrix. Network-loss cases forward to real CAD before injecting a client fault."""
import json
import socket
import time
from uuid import uuid4
from autocad_mcp.cad.backends.com_backend import COMBackend
from autocad_mcp.cad.backends.http_backend import BridgeRemoteError
from .native import wait_for
from .soak import signature
from .common import LAYER

LINE={"start":[0,0,0],"end":[10,0,0],"layer":LAYER}

def faults(native,selected=None):
    results=[]
    def fresh(timeout=30):
        backend,traffic=native.backend(timeout)
        name,docid=native.new_document(backend)
        backend.execute("create_layer",{"name":LAYER,"color":4})
        return backend,traffic,name,docid
    def state(backend):
        return (sorted(signature(r) for r in backend.execute("query_entities",{})),
                sorted(backend.execute("list_layers",{})))
    def error(callback,code,outcome=None):
        try:
            callback()
        except BridgeRemoteError as exc:
            assert exc.code==code,(exc.code,code)
            if outcome:
                assert exc.outcome==outcome,(exc.outcome,outcome)
            return exc
        raise AssertionError("Expected error was not raised")
    def case(name,callback):
        if selected is not None and name not in selected:
            results.append(dict(case=name,status="not_run",reason="Not selected for this focused run"))
            return
        initial=set(native.owned)
        start=time.perf_counter()
        cleanup_error=None
        try:
            evidence=callback()
            row=dict(case=name,status="passed",evidence=evidence)
        except Exception as exc:
            row=dict(case=name,status="failed",error_type=type(exc).__name__,error_code=getattr(exc,"code",None))
            if isinstance(exc,(AssertionError,ValueError)):
                row["detail"]=str(exc)[:500]
        finally:
            try:
                native.idle()
                for name2 in sorted(native.owned-initial,reverse=True):
                    native.close_document(name2)
            except Exception as exc:
                cleanup_error=exc
                row["execution_status"]=row["status"]
                row.update(status="failed",error_phase="cleanup",cleanup_error_type=type(exc).__name__)
        row["elapsed_ms"]=(time.perf_counter()-start)*1000
        native.records.add("fault",**row)
        results.append(row)
        native.records.json("faults.json",{"cases":results,"completed":False})
        print(json.dumps({"phase":"fault","case":name,"status":row["status"]}),flush=True)
        if cleanup_error:
            raise RuntimeError("Fault cleanup failed; see preserved case evidence") from cleanup_error
        native.restart()
    def authentication():
        a=native.raw.get("/v1/health",headers={"Authorization":"Bearer invalid"})
        b=native.raw.get("/v1/health",headers={"Origin":"http://example.test"})
        c=native.raw.get("/v1/health",headers={"Host":"localhost:"+str(native.port)})
        assert (a.status_code,b.status_code,c.status_code)==(401,403,403)
        return dict(auth_status=a.status_code,origin_status=b.status_code,host_status=c.status_code)
    case("authentication_origin_host",authentication)
    def invalid_geometry():
        h,_,_,_=fresh()
        try:
            before=state(h)
            for op,args in [("draw_circle",{"center":[0,0,0],"radius":-1}),
                            ("draw_line",{"start":[0,0,0],"end":[0,0,0]}),
                            ("draw_line",{**LINE,"layer":"MISSING_LAYER"})]:
                error(lambda:h.execute(op,args),"INVALID_ARGUMENT","rolled_back")
                assert state(h)==before
            return {"rejected":3,"additional_entities":0,"layer_changes":0}
        finally:
            h.close()
    case("invalid_geometry_no_residue",invalid_geometry)
    for position in (0,2,4):
        def rollback(position=position):
            h,_,_,_=fresh()
            try:
                before=state(h)
                ops=[{"id":"layer","operation":"create_layer","args":{"name":"ROLLBACK_ONLY"}},
                     {"id":"line1","operation":"draw_line","args":{**LINE,"layer":"ROLLBACK_ONLY"}},
                     {"id":"circle1","operation":"draw_circle","args":{"center":[20,0,0],"radius":3,"layer":"ROLLBACK_ONLY"}},
                     {"id":"line2","operation":"draw_line","args":{"start":[0,2,0],"end":[10,2,0],"layer":"ROLLBACK_ONLY"}},
                     {"id":"circle2","operation":"draw_circle","args":{"center":[30,0,0],"radius":3,"layer":"ROLLBACK_ONLY"}}]
                failed_id=ops[position]["id"]
                ops[position]={"id":failed_id,"operation":"draw_circle","args":{"center":[0,0,0],"radius":-1}}
                rid=uuid4().hex
                error(lambda:h.execute_batch(ops,request_id=rid),"INVALID_ARGUMENT","rolled_back")
                assert state(h)==before
                terminal=h.get_job(rid)
                assert terminal.error.failed_operation_id==failed_id
                return dict(failed_index=position,terminal_status=terminal.status,additional_entities=0,layer_changes=0)
            finally:
                h.close()
        case("atomic_rollback_"+str(position),rollback)
    def dedup():
        h,_,_,_=fresh()
        try:
            rid=uuid4().hex
            first=h.execute("draw_line",LINE,request_id=rid)
            assert h.execute("draw_line",LINE,request_id=rid)==first
            error(lambda:h.execute("draw_line",{**LINE,"end":[20,0,0]},request_id=rid),"REQUEST_ID_CONFLICT")
            assert len(h.execute("query_entities",{}))==1
            return dict(submissions=3,entities=1,duplicate_side_effects=0,conflict_rejected=True)
        finally:
            h.close()
    case("deduplication_and_request_conflict",dedup)
    def binding():
        a,_,aname,_=fresh()
        com=COMBackend(native.config)
        com.execute("list_layers",{})
        b,_,bname,_=fresh()
        try:
            a.execute("draw_line",LINE)  # B is active, A remains the bound write target.
            try:
                com.execute("draw_line",LINE)
                raise AssertionError("COM silently retargeted")
            except Exception as exc:
                if type(exc).__name__!="CADDocumentChangedError":
                    raise
            assert len(a.execute("query_entities",{}))==1 and b.execute("query_entities",{})==[]
            return dict(http_bound_target_respected=True,com_switched_document_rejected=True,wrong_document_writes=0)
        finally:
            com.close();a.close();b.close()
    case("active_document_switch_both_backends",binding)
    def document_close():
        a,_,aname,aid=fresh()
        alias=a.execute("draw_line",LINE)
        b,_,_,_=fresh()
        try:
            native.close_document(aname)
            error(lambda:a.execute("query_entities",{}),"DOCUMENT_NOT_FOUND")
            error(lambda:a.execute("get_entity",{"object_id":alias}),"DOCUMENT_NOT_FOUND")
            error(lambda:b.execute("get_entity",{"object_id":999999999}),"ENTITY_NOT_FOUND")
            assert b.execute("query_entities",{})==[]
            rid=uuid4().hex
            native.raw.post("/v1/execute",json={"request_id":rid,"document_id":"invalid-session",
                "operation":"draw_line","args":LINE})
            result=native.poll(rid)
            assert result["error"]["code"]=="DOCUMENT_NOT_FOUND"
            return dict(closed_document_rejected=True,wrong_session_rejected=True,wrong_document_writes=0)
        finally:
            a.close();b.close()
    case("closed_document_stale_id_and_wrong_session",document_close)
    def revision():
        from autocad_mcp.cad.geometry import to_variant_point
        h,_,name,_=fresh()
        try:
            status=h.status()
            rev=next(d["revision"] for d in status["documents"] if d["name"]==name)
            doc=native.app.Documents.Item(name)
            doc.ModelSpace.AddLine(to_variant_point(1,1,0),to_variant_point(2,1,0))
            error(lambda:h.execute("draw_line",LINE,expected_revision=rev),"REVISION_CONFLICT")
            rows=h.execute("query_entities",{})
            assert len(rows)==1 and rows[0]["start_point"]==[1,1,0]
            return dict(external_com_edit_observed=True,stale_write_rejected=True,entities=1)
        finally:
            h.close()
    case("external_edit_revision_conflict",revision)
    def lost_response():
        h,traffic,_,_=fresh()
        try:
            traffic.reset();traffic.drop_post=True
            rid=uuid4().hex
            error(lambda:h.execute("draw_line",LINE,request_id=rid),"OUTCOME_UNKNOWN","outcome_unknown")
            assert traffic.posts==1
            result=native.poll(rid)
            assert result["status"]=="succeeded"
            rows=h.execute("query_entities",{})
            assert len(rows)==1
            return dict(injection="response discarded after forwarding real POST",write_posts=1,
                final_status=result["status"],entities=1,duplicate_side_effects=0)
        finally:
            h.close()
    case("lost_post_response_no_replay",lost_response)
    for fault in ("poll_disconnect","wait_timeout"):
        def pending(fault=fault):
            h,traffic,_,_=fresh(timeout=5)
            try:
                traffic.reset()
                if fault=="wait_timeout":
                    # Reduce only the job wait budget after fixture creation/handshake.
                    h._config.request_timeout_seconds=.25
                native.busy()
                traffic.drop_poll=fault=="poll_disconnect"
                rid=uuid4().hex
                try:
                    error(lambda:h.execute("draw_line",LINE,request_id=rid),"OUTCOME_UNKNOWN","outcome_unknown")
                    assert traffic.posts==1
                    queued=native.raw.get("/v1/jobs/"+rid).json()
                    assert queued["status"]=="queued"
                finally:
                    native.idle()
                terminal=native.poll(rid)
                assert terminal["status"]=="succeeded"
                assert len(h.execute("query_entities",{}))==1
                return dict(write_posts=1,pending_status=queued["status"],recovered_status=terminal["status"],
                    entities=1,duplicate_side_effects=0)
            finally:
                h.close()
        case(fault+"_no_replay",pending)
    def queue_full():
        h,_,_,docid=fresh()
        ids=[]
        try:
            native.busy()
            try:
                responses=[]
                for _ in range(70):
                    rid=uuid4().hex;ids.append(rid)
                    responses.append(native.raw.post("/v1/execute",json={"request_id":rid,"document_id":docid,
                        "operation":"query_entities","args":{}}).json())
                queued=sum(r.get("status")=="queued" for r in responses)
                rejected=[r for r in responses if (r.get("error") or {}).get("code")=="QUEUE_FULL"]
                assert queued==64 and len(rejected)==6,(queued,len(rejected))
                assert all(r["error"]["outcome"]=="not_executed" for r in rejected)
            finally:
                native.idle()
            terminal=[native.poll(rid) for rid in ids]
            assert sum(r["status"]=="succeeded" for r in terminal)==64
            return dict(queued=queued,rejected=len(rejected),terminal=len(terminal),hanging_jobs=0)
        finally:
            h.close()
    case("busy_queue_capacity_and_drain",queue_full)
    def stop_with_pending_write():
        from concurrent.futures import ThreadPoolExecutor
        h,traffic,name,docid=fresh()
        rid=uuid4().hex
        try:
            native.busy(stop=True)
            traffic.reset()
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending=pool.submit(h.execute,"draw_line",LINE,request_id=rid)
                wait_for(lambda:traffic.posts==1)
                queued=wait_for(lambda:(lambda r:r if r.get("status")=="queued" else None)(native.raw.get("/v1/jobs/"+rid).json()))
                native.idle()  # The fixed-duration test command stops Bridge before returning to Idle.
                try:
                    pending.result(timeout=10)
                    outcome="succeeded_before_stop"
                except BridgeRemoteError as exc:
                    assert exc.code=="OUTCOME_UNKNOWN" or (exc.code=="CAD_BUSY" and exc.outcome=="not_executed")
                    outcome=exc.outcome
            assert traffic.posts==1
            native.start()
            readback,_=native.backend()
            try:
                rows=readback.execute("query_entities",{})
                assert len(rows)<=1 and all(signature(r)==("line",LAYER,(0,0,0),(10,0,0)) for r in rows)
            finally:
                readback.close()
            return dict(initial_status=queued["status"],client_outcome=outcome,write_posts=1,
                observed_entities=len(rows),duplicate_side_effects=0)
        finally:
            h.close()
    case("stop_with_pending_write_and_readback",stop_with_pending_write)
    def journal_full():
        h,_,_,_=fresh()
        successful=0
        try:
            for _ in range(2050):
                try:
                    h.execute("query_entities",{})
                    successful+=1
                except BridgeRemoteError as exc:
                    assert exc.code=="QUEUE_FULL" and exc.outcome=="not_executed"
                    break
            else:
                raise AssertionError("Journal did not enforce its configured capacity")
            assert 2000<=successful<=2048
            native.restart()
            recovery,_=native.backend()
            try:
                native.new_document(recovery)
                assert recovery.execute("query_entities",{})==[]
            finally:
                recovery.close()
            return dict(successful_queries_before_limit=successful,capacity=2048,
                overflow_code="QUEUE_FULL",explicit_restart_recovered=True)
        finally:
            h.close()
    case("journal_capacity_and_explicit_recovery",journal_full)
    def lifecycle():
        h,_,_,_=fresh()
        instances=[native.instance]
        try:
            for _ in range(3):
                native.restart()
                instances.append(native.instance)
            error(lambda:h.execute("query_entities",{}),"OUTCOME_UNKNOWN")
            fresh_client,_=native.backend()
            try:
                error(lambda:fresh_client.execute("draw_line",LINE),"FORBIDDEN")
                native.new_document(fresh_client)
                fresh_client.execute("draw_line",{"start":[1,2,0],"end":[3,4,0]})
                assert len(fresh_client.execute("query_entities",{}))==1
            finally:
                fresh_client.close()
            return dict(distinct_instances=len(set(instances)),old_client_rejected=True,new_client_recovered=True)
        finally:
            h.close()
    case("bridge_restart_instance_and_ownership",lifecycle)
    def port_conflict():
        native.stop()
        with socket.socket() as occupied:
            occupied.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            occupied.bind(("127.0.0.1",native.port));occupied.listen(1)
            native.command("MCPBRIDGE_START\n")
            time.sleep(.5)
            assert native.pid in __import__("scripts.verify_http_bridge",fromlist=["cad_processes"]).cad_processes()
        native.start()
        h,_=native.backend()
        try:
            h.status()
        finally:
            h.close()
        return dict(cad_survived=True,port_release_recovered=True)
    case("port_conflict_and_recovery",port_conflict)
    results.append(dict(case="cad_process_restart",status="not_run",
        reason="User-owned running CAD preserved. Requires an independently owned empty instance and normal desktop restart."))
    result=dict(completed=True,passed=all(r["status"]=="passed" for r in results if r["status"]!="not_run"),
        cases=results,limitations=["Network loss is injected at the client transport boundary against real accepted jobs",
            "Database revision edit uses external COM, not a human UI edit",
            "Crash recovery and persistent journal are not implemented","CAD process restart not run in a user-owned instance"])
    native.records.json("faults.json",result)
    return result
