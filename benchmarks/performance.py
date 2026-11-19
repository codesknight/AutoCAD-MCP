"""Paired backend benchmarks; setup, validation and cleanup are outside timing."""
import json
import math
import random
import time
from autocad_mcp.cad.backends.com_backend import COMBackend
from .common import LAYER,fixture,geometry_check
from .native import memory

def populate(backend,count):
    operations=[{"id":str(i),"operation":"draw_line","args":p} for i,p in enumerate(fixture(count))]
    for offset in range(0,len(operations),200):
        backend.execute_batch(operations[offset:offset+200])

def trial(native,scenario,size,backend_name,mode,phase,index):
    native.restart()  # Outside timing; avoid the 2048-record/10-minute journal capacity confound.
    creator,traffic=native.backend()
    backend=None
    name=None
    row=dict(scenario=scenario,size=size,backend=backend_name,mode=mode,phase=phase,index=index,ok=False)
    try:
        name,_=native.new_document(creator)
        creator.execute("create_layer",{"name":LAYER,"color":4})
        if scenario=="query":
            populate(creator,size)
        backend=creator if backend_name=="http" else COMBackend(native.config)
        if scenario!="cold_attach":
            backend.execute("list_layers",{})  # Warm connection/STA construction, not part of the hot sample.
        else:
            # The fixture creator has a separate connection; this adapter starts completely cold.
            if backend_name=="http":
                backend,traffic=native.backend()
        traffic.reset()
        row["memory_before"]=memory(native.pid)
        start=time.perf_counter()
        try:
            if scenario=="query":
                rows=backend.execute("query_entities",{})
                operation_count=1
            elif scenario=="cold_attach":
                layers=backend.execute("list_layers",{})
                operation_count=1
            elif mode=="batch":
                populate(backend,size)
                operation_count=math.ceil(size/200)
            else:
                for payload in fixture(size):
                    backend.execute("draw_line",payload)
                operation_count=size
            row["elapsed_ms"]=(time.perf_counter()-start)*1000
        except Exception:
            row["elapsed_ms"]=(time.perf_counter()-start)*1000
            raise
        row["memory_after"]=memory(native.pid)
        if backend_name=="http":
            row.update(traffic.snapshot())
        row["adapter_calls"]=operation_count
        if scenario=="cold_attach":
            if LAYER not in layers:
                raise ValueError("Cold attachment returned the wrong drawing layers")
            row["validated_layer"]=True
        else:
            if scenario!="query":
                rows=creator.execute("query_entities",{})
            row.update(geometry_check(rows,size))
        row["ok"]=True
    except Exception as exc:
        row.update(error_type=type(exc).__name__,error_code=getattr(exc,"code",None),
            outcome=getattr(exc,"outcome",None))
        if isinstance(exc,(AssertionError,ValueError)):
            row["detail"]=str(exc)[:500]
        if "elapsed_ms" not in row:
            row["elapsed_ms"]=0.0
            row["setup_failed"]=True
    finally:
        if backend is not None and backend is not creator:
            backend.close()
        creator.close()
        if name is not None:
            native.close_document(name)
        native.records.add("benchmark",**row)
    return row

def benchmark(native,args):
    rng=random.Random(args.seed)
    plans=[]
    total=0
    failed=0
    warmup_failed=0
    def group(scenario,size,modes):
        nonlocal total,failed,warmup_failed
        warm=[]
        for i in range(args.warmups):
            order=modes.copy()
            rng.shuffle(order)
            for backend,mode in order:
                warm.append(trial(native,scenario,size,backend,mode,"warmup",i))
        slow=max(r["elapsed_ms"] for r in warm)/1000
        warmup_failed+=sum(not r["ok"] for r in warm)
        heavy=scenario!="cold_attach" and slow>args.heavy_threshold
        repetitions=args.heavy_samples if heavy else args.samples
        reason=(f"Paired warmup max {slow:.3f}s exceeds declared {args.heavy_threshold}s heavy threshold; "
                f"use {repetitions} repeats for every mode in this group") if heavy else "Standard repetition count"
        plan=dict(scenario=scenario,size=size,samples=repetitions,warmups=args.warmups,
                  paired_warmup_max_seconds=slow,reason=reason)
        native.records.add("benchmark_plan",**plan)
        plans.append(plan)
        print(json.dumps({"phase":"benchmark",**plan}),flush=True)
        for i in range(repetitions):
            if (native.records.directory/"STOP").exists():
                raise InterruptedError("Qualification stopped by operator")
            order=modes.copy()
            rng.shuffle(order)
            for backend,mode in order:
                row=trial(native,scenario,size,backend,mode,"measured",i)
                total+=1
                failed+=int(not row["ok"])
            print(json.dumps({"phase":"benchmark","scenario":scenario,"size":size,
                "repeat":i+1,"of":repetitions,"failures":failed}),flush=True)
    group("cold_attach",0,[("com","single"),("http","single")])
    for size in args.sizes:
        group("query",size,[("com","single"),("http","single")])
        group("create",size,[("com","single"),("http","single"),("http","batch")])
    result=dict(completed=True,passed=failed==0 and warmup_failed==0,measured_samples=total,
        failed_samples=failed,warmup_failed=warmup_failed,groups=plans,
        timing_boundary="Python adapter.execute/execute_batch, excluding fixture provisioning, validation, explicit regen/save and cleanup",
        instance_policy="Fresh Bridge instance and fresh acadiso.dwt document per sample, outside timing",
        statistics_policy="P95 only for >=20 successful measured samples; heavy groups expose median/max and sample count",
        fairness="Same fixture, CAD process/build, unit/layer, normalized query fields, seed-shuffled mode order",
        exclusions=["LLM latency","MCP transport overhead","CAD process cold startup","atomicity equivalence for COM sequential writes"])
    native.records.json("benchmark.json",result)
    return result
