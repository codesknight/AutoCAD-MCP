"""Optional scientific plot from recorded benchmark CSV; requires matplotlib only for authoring."""
import argparse
import csv
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rows=list(csv.DictReader(args.summary.open(encoding="utf-8")))
    sizes=sorted({int(r["size"]) for r in rows if r["scenario"]!="cold_attach"})
    colors={"com":"#386cb0","http":"#f49b32","batch":"#20a486"}
    fig,axes=plt.subplots(1,2,figsize=(11.8,4.4),layout="constrained")
    for ax,scenario,modes,title in [
        (axes[0],"query",[("com","single","COM"),("http","single","HTTP")],"Query the same line fixture"),
        (axes[1],"create",[("com","single","COM sequential"),("http","single","HTTP sequential"),("http","batch","HTTP batch")],"Create the same line fixture"),
    ]:
        width=.23
        for j,(backend,mode,label) in enumerate(modes):
            values=[];counts=[]
            for size in sizes:
                r=next(r for r in rows if r["scenario"]==scenario and int(r["size"])==size and r["backend"]==backend and r["mode"]==mode)
                values.append(float(r["median_ms"]) if r["median_ms"] else float("nan"))
                counts.append((int(r["passed"]),int(r["failed"])))
            xpos=[i+(j-(len(modes)-1)/2)*width for i in range(len(sizes))]
            bars=ax.bar(xpos,values,width,label=label,color=colors["batch" if mode=="batch" else backend])
            for bar,value,(valid,failed) in zip(bars,values,counts):
                if not valid:
                    ax.annotate(f"0 valid\n{failed} failed",(bar.get_x()+bar.get_width()/2,.08),
                        xycoords=("data","axes fraction"),ha="center",fontsize=7,color="#a33")
                    continue
                ax.annotate(f"{value:,.1f}\nvalid={valid}, fail={failed}",(bar.get_x()+bar.get_width()/2,value),
                    xytext=(0,4),textcoords="offset points",ha="center",va="bottom",fontsize=7)
        ax.set_xticks(range(len(sizes)),[f"{n:,}" for n in sizes])
        ax.set_xlabel("Entities")
        ax.set_ylabel("Median adapter elapsed time (ms, log scale)")
        ax.set_yscale("log")
        ax.set_ylim(top=ax.get_ylim()[1]*2.2)
        ax.set_title(title,fontsize=11)
        ax.legend(loc="upper left",fontsize=8,frameon=False)
        ax.grid(axis="y",which="major",alpha=.18)
        ax.set_axisbelow(True)
    fig.suptitle("AutoCAD 2026 / COM vs experimental HTTP Bridge",fontsize=14)
    fig.supxlabel("Medians use validated samples only; all failed attempts remain reported. Setup/verification/LLM latency excluded.",fontsize=8)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(args.output,metadata={"Date":None})
    if args.output.suffix.lower()==".svg":
        args.output.write_text("\n".join(line.rstrip() for line in args.output.read_text(encoding="utf-8").splitlines())+"\n",encoding="utf-8")
    plt.close(fig)

if __name__=="__main__":
    main()
