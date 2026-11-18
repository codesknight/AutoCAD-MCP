"""Opt-in CAD-09 qualification. Run from the repository root with python -m benchmarks.run."""
import argparse
from pathlib import Path
import traceback
from .common import Records,write_summary

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--mode",choices=["all","faults","benchmark","soak"],default="all")
    parser.add_argument("--owned-pid",type=int,help="Only this explicitly owned CAD process may be closed")
    parser.add_argument("--preserve-existing",action="store_true",help="Keep existing drawings, create scratch documents and restore the active drawing")
    parser.add_argument("--soak-seconds",type=float,default=1800)
    parser.add_argument("--interval",type=float,default=1)
    parser.add_argument("--sizes",type=int,nargs="+",default=[100,500,1000])
    parser.add_argument("--samples",type=int,default=20)
    parser.add_argument("--heavy-samples",type=int,default=5)
    parser.add_argument("--heavy-threshold",type=float,default=5,help="Seconds; classify the whole paired group from warmups")
    parser.add_argument("--warmups",type=int,default=3)
    parser.add_argument("--seed",type=int,default=190019)
    args=parser.parse_args()
    if args.soak_seconds<0 or args.interval<0 or args.samples<1 or args.heavy_samples<1 or args.warmups<1 or any(n<1 or n>1000 for n in args.sizes):
        parser.error("Invalid sample counts, durations or supported fixture sizes")
    records=Records(args.output)
    records.json("plan.json",{k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()})
    from .native import Native
    native=Native.__new__(Native)
    completed=False
    result={"completed":False}
    try:
        native.__init__(records,args.owned_pid,args.preserve_existing)
        records.json("environment.json",native.environment())
        if args.mode in ("all","faults"):
            from .faults import faults
            result["faults"]=faults(native)
        if args.mode in ("all","benchmark"):
            from .performance import benchmark
            result["benchmark"]=benchmark(native,args)
        if args.mode in ("all","soak"):
            from .soak import soak
            result["soak"]=soak(native,args.soak_seconds,args.interval)
        completed=True
    except Exception as exc:
        result.update(error_type=type(exc).__name__,error_code=getattr(exc,"code",None))
        records.add("run_failure",error_type=type(exc).__name__,error_code=getattr(exc,"code",None))
        traceback.print_exc()
    finally:
        if hasattr(native,"owned"):
            try:
                result["cleanup"]=native.close()
            except Exception as exc:
                result["cleanup"]={"error_type":type(exc).__name__}
                traceback.print_exc()
        rows,summary=write_summary(records)
        result["completed"]=completed and result.get("cleanup",{}).get("listener_stopped",False) and not result.get("cleanup",{}).get("remaining_documents",[]) and "error_type" not in result.get("cleanup",{})
        result["summary"]=summary
        records.json("qualification.json",result)
    if not result["completed"]:
        raise SystemExit(1)
    print("Qualification completed; all owned drawings cleaned.",flush=True)

if __name__=="__main__":
    main()
