"""Opt-in real COM lifecycle/receipt checks. New scratch documents only.

Adapter fault hooks suppress a real native return or fail a post-ACK read; they
are explicitly distinct from an AutoCAD crash or an actual busy HRESULT. No
unknown write is retried, and no existing document is mutated or closed.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4

import pythoncom
import win32com.client
import win32process

from autocad_mcp.cad import execution
from autocad_mcp.cad.backends.com_backend import COMBackend, COMSession
from autocad_mcp.cad.capture import method, prop
from autocad_mcp.cad.query import _entity_summary
from autocad_mcp.config import load_config


def snapshot(app):
    docs=prop(app,"Documents");rows=[]
    for i in range(prop(docs,"Count")):
        doc=method(docs,"Item")(i)
        entities=[_entity_summary(e) for e in prop(doc,"ModelSpace")]
        rows.append(dict(name=prop(doc,"Name"),path=prop(doc,"FullName"),entities=entities))
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-pid",type=int,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--native-fixture",action="store_true",help="Attach only through the dedicated NativeTests ROT identity")
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    pythoncom.CoInitialize();config=load_config()
    if args.native_fixture:
        from scripts.native_test_target import Busy, application
        win32com.client.GetActiveObject=lambda _:application(args.expected_pid)
    app=win32com.client.GetActiveObject(config.prog_id)
    assert win32process.GetWindowThreadProcessId(prop(app,"HWND"))[1]==args.expected_pid
    assert prop(method(app,"GetAcadState")(),"IsQuiescent")
    original=prop(app,"ActiveDocument");before=snapshot(app)
    (out/"before.json").write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding="utf-8")
    sessions=[]
    def factory(cfg):
        session=COMSession(cfg,attach_only=True);sessions.append(session);return session
    backend=COMBackend(config,session_factory=factory);calls=[];owned=[]
    report=dict(passed=False,completed=False,process_id=args.expected_pid,
                injection="adapter_return_and_post_read_hooks_over_real_native_mutations")
    def call(op,values,doc=None):
        value=backend.execute_evidenced(op,values,request_id=uuid4().hex,
                    instance_id=backend.instance_id,document_id=doc)
        calls.append(value);(out/"calls.json").write_text(json.dumps(calls,ensure_ascii=False,indent=2),encoding="utf-8")
        return value
    def new():
        answer=call("new_document",{})
        assert answer["receipt"]["status"]=="succeeded",answer
        doc=prop(app,"ActiveDocument");owned.append(doc)
        return answer["receipt"]["result_document_id"],doc
    try:
        first,doc1=new()
        a=out/"a";a.mkdir();b=out/"b";b.mkdir()
        assert call("save_drawing",dict(file_path=str(a/"same.dwg")),first)["receipt"]["status"]=="succeeded"
        second,doc2=new()
        assert call("save_drawing",dict(file_path=str(b/"same.dwg")),second)["receipt"]["status"]=="succeeded"
        assert prop(doc1,"Name")==prop(doc2,"Name")=="same.dwg" and first!=second
        method(doc1,"Activate")()
        rejected=call("draw_line",dict(start=[0,0,0],end=[10,0,0]),second)
        assert rejected["receipt"]["stage"]=="not_dispatched"
        assert not rejected["receipt"]["native_invoked"]
        method(doc2,"Activate")()
        good=call("draw_line",dict(start=[0,0,0],end=[10,0,0]),second)
        assert good["receipt"]["status"]=="succeeded",good
        own_id=good["result"]
        assert call("get_entity",dict(object_id=own_id),second)["receipt"]["status"]=="succeeded"
        moved=call("move_entity",dict(object_id=own_id,offset=[0,1,0]),second)
        assert moved["receipt"]["affected_entities"]["modified"]==[str(own_id)]
        # Document.ObjectIdToObject must not grant access to a foreign database.
        from autocad_mcp.cad.geometry import to_variant_point
        foreign=method(prop(doc1,"ModelSpace"),"AddLine")(to_variant_point(0,50,0),to_variant_point(10,50,0))
        foreign_id=prop(foreign,"ObjectID")
        refused=call("move_entity",dict(object_id=foreign_id,offset=[100,0,0]),second)
        assert refused["receipt"]["stage"]=="not_dispatched" and not refused["receipt"]["native_invoked"]
        assert list(prop(foreign,"StartPoint"))==[0,50,0]
        temporary=call("draw_line",dict(start=[60,0,0],end=[70,0,0]),second)
        deleted=call("delete_entity",dict(object_id=temporary["result"]),second)
        assert deleted["receipt"]["affected_entities"]["deleted"]==[str(temporary["result"])]
        # A real AddLine succeeds; suppress its return before native_action records ACK.
        native=execution.native_action
        def lose(name,action):
            if name=="AddLine":
                def effect_then_lose():
                    action()
                    raise RuntimeError("TEST_INJECTION: real AddLine return suppressed before ACK recording")
                return native(name,effect_then_lose)
            return native(name,action)
        execution.native_action=lose
        try:lost=call("draw_line",dict(start=[30,0,0],end=[40,0,0]),second)
        finally:execution.native_action=native
        assert lost["receipt"]["stage"]=="result_unknown" and not lost["receipt"]["native_acknowledged"]
        rows=backend.execute("query_entities",{})
        assert len(rows)==2 and any(r.get("start_point")==[30,0,0] for r in rows)
        report["lost_ack_independent_entities"]=rows
        assert backend.execution_status(backend.instance_id,lost["receipt"]["request_id"])==lost["receipt"]
        # Never continue writing in this unknown scratch. A different new document is used.
        third,doc3=new();session=sessions[0];real=session.connection.binding;seen=[]
        def post_read_fault():
            seen.append(1)
            if len(seen)==2:raise RuntimeError("TEST_INJECTION: post-ACK binding read unavailable")
            return real()
        session.connection.binding=post_read_fault
        try:acked=call("draw_line",dict(start=[0,20,0],end=[20,20,0]),third)
        finally:session.connection.binding=real
        assert acked["receipt"]["stage"]=="observation_failed" and acked["receipt"]["native_acknowledged"]
        assert len(backend.execute("query_entities",{}))==1
        if args.native_fixture:
            fourth,doc4=new();hold=[]
            def real_busy_after_ack(name,action):
                value=native(name,action)
                if name=="AddLine":
                    busy=Busy(args.expected_pid);busy.__enter__();hold.append(busy)
                return value
            execution.native_action=real_busy_after_ack
            clock=time.monotonic()
            try:
                busy_result=call("draw_line",dict(start=[0,40,0],end=[20,40,0]),fourth)
            finally:
                execution.native_action=native
                for busy in hold:busy.__exit__(None,None,None)
            receipt=busy_result["receipt"]
            elapsed=time.monotonic()-clock
            assert receipt["native_acknowledged"],receipt
            # Direct IDispatch property reads may wait for the native hold and
            # succeed. Do not require or invent an HRESULT that CAD did not emit.
            assert receipt["stage"] in {"observation_failed","completed"},receipt
            assert len(backend.execute("query_entities",{}))==1
            report["actual_native_busy"]=dict(stage=receipt["stage"],elapsed_seconds=elapsed,
                hresult=(receipt["error"] or {}).get("hresult"),native_write_calls=len(receipt["native_actions"]))
        old_instance=backend.instance_id;backend.close();fresh=COMBackend(config)
        try:
            absent=fresh.execution_status(old_instance,lost["receipt"]["request_id"])
            assert absent["status"]=="unresolved" and absent["replay_safe"] is False
            report["fresh_backend_lookup"]=absent
        finally:fresh.close()
        report["passed"]=True
    except Exception as error:
        report["error"]=dict(type=type(error).__name__,message=str(error))
        raise
    finally:
        backend.close()
        # Only explicit scratch references from successful new-document receipts.
        for doc in reversed(owned):method(doc,"Close")(False)
        method(original,"Activate")()
        after=snapshot(app)
        report["original_documents_unchanged"]=(before==after)
        report["completed"]=True
        report["before_sha256"]=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest()
        report["after_sha256"]=hashlib.sha256(json.dumps(after,sort_keys=True).encode()).hexdigest()
        (out/"qualification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        assert report["original_documents_unchanged"]
    print(json.dumps({k:report[k] for k in ["passed","completed","original_documents_unchanged"]}))


if __name__=="__main__":main()
