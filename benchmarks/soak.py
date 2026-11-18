"""Bounded mixed workload; no artificial failure injection during the soak."""
import json
import math
import time
from .common import LAYER, fixture
from .native import memory

def signature(row):
    if row["type"]=="AcDbLine":
        return ("line",row["layer"],tuple(row["start_point"]),tuple(row["end_point"]))
    if row["type"]=="AcDbCircle":
        return ("circle",row["layer"],tuple(row["center"]),row["radius"])
    raise ValueError("Unexpected soak entity")

def soak(native, seconds=1800, interval=1):
    records=native.records
    start=time.monotonic()
    baseline=memory(native.pid)
    count=0
    samples=[]
    backend=None
    name=None
    expected=[]
    ids=[]
    last_progress=-60
    try:
        while time.monotonic()-start<seconds or count<1000:
            if (records.directory/"STOP").exists():
                raise InterruptedError("Qualification stopped by operator")
            if count%500==0:
                if backend:
                    backend.close()
                    native.close_document(name)
                backend,traffic=native.backend()
                name,_=native.new_document(backend)
                backend.execute("create_layer",{"name":LAYER,"color":4})
                expected=[]
                ids=[]
            op=count%5
            before=time.perf_counter()
            operation=("draw_line","list_layers","query_entities","get_entity","draw_circle")[op]
            try:
                if op==0:
                    args=fixture(len(expected)+1)[-1]
                    entity=backend.execute(operation,args)
                    expected.append(("line",LAYER,tuple(args["start"]),tuple(args["end"])))
                    ids.append(entity)
                elif op==1:
                    if LAYER not in backend.execute(operation,{}):
                        raise ValueError("Fixture layer disappeared")
                elif op==2:
                    rows=backend.execute(operation,{})
                    if sorted(signature(r) for r in rows)!=sorted(expected):
                        raise ValueError("Soak geometry changed unexpectedly")
                elif op==3:
                    if signature(backend.execute(operation,{"object_id":ids[-1]}))!=expected[-1]:
                        raise ValueError("Entity lookup returned wrong geometry")
                else:
                    args={"center":[float(len(expected)),7.0,0.0],"radius":2.0,"layer":LAYER}
                    entity=backend.execute(operation,args)
                    expected.append(("circle",LAYER,tuple(args["center"]),2.0))
                    ids.append(entity)
                elapsed=(time.perf_counter()-before)*1000
                records.add("soak",operation=operation,index=count,ok=True,elapsed_ms=elapsed)
                samples.append(elapsed)
                count+=1
            except Exception as exc:
                records.add("soak",operation=operation,index=count,ok=False,
                    elapsed_ms=(time.perf_counter()-before)*1000,error_type=type(exc).__name__,
                    error_code=getattr(exc,"code",None))
                raise
            now=time.monotonic()-start
            if now-last_progress>=60:
                usage=memory(native.pid)
                records.add("soak_resource",elapsed_seconds=now,calls=count,**usage)
                print(json.dumps({"phase":"soak","elapsed_seconds":round(now),"calls":count,
                    "private_mib":round(usage["private_bytes"]/1048576,1)}),flush=True)
                last_progress=now
                if usage["private_bytes"]-baseline["private_bytes"]>512*1048576:
                    raise RuntimeError("Soak private memory growth exceeded the declared 512 MiB stop budget")
            time.sleep(max(0,interval-(time.perf_counter()-before)))
        result=dict(completed=True,duration_seconds=time.monotonic()-start,successful_calls=count,
            failed_calls=0,interval_seconds=interval,memory_start=baseline,memory_end=memory(native.pid),
            stop_budget_private_growth_bytes=512*1048576,
            p50_ms=sorted(samples)[len(samples)//2],p95_ms=sorted(samples)[math.ceil(.95*len(samples))-1])
        records.json("soak.json",result)
        return result
    finally:
        if backend:
            backend.close()
        if name:
            native.close_document(name)
