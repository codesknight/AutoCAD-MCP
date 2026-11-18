"""Pure-data fixtures, validation and reporting shared by native qualification."""
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

LAYER = "CAD09_FIXTURE"

def fixture(count):
    return [{"start": [float(i % 50 * 3), float(i // 50 * 3), 0.0],
             "end": [float(i % 50 * 3 + 1), float(i // 50 * 3 + 2), 0.0],
             "layer": LAYER} for i in range(count)]

def normalized(rows):
    result = []
    for row in rows:
        if row["type"] != "AcDbLine":
            raise ValueError("Unexpected entity type")
        item = {"type": row["type"], "layer": row["layer"]}
        for key in ("start_point", "end_point"):
            values = row[key]
            if len(values) != 3 or any(not math.isfinite(v) for v in values):
                raise ValueError("Invalid point")
            item[key] = [round(float(v), 8) for v in values]
        item["bounding_box"] = {
            "min": [round(float(v), 8) for v in row["bounding_box"]["min"]],
            "max": [round(float(v), 8) for v in row["bounding_box"]["max"]],
        }
        result.append(item)
    return sorted(result, key=lambda r: (r["start_point"], r["end_point"], r["layer"]))

def expected(count):
    return normalized([dict(type="AcDbLine", layer=LAYER, start_point=p["start"], end_point=p["end"],
        bounding_box={"min":p["start"], "max":p["end"]}) for p in fixture(count)])

def geometry_check(rows, count):
    actual, wanted = normalized(rows), expected(count)
    if len(actual) != len(wanted):
        raise ValueError(f"Entity count mismatch: {len(actual)} != {count}")
    def equal(a,b):
        if isinstance(a, dict):
            return a.keys() == b.keys() and all(equal(a[k],b[k]) for k in a)
        if isinstance(a, list):
            return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
        if isinstance(a, (int,float)):
            return math.isclose(a,b,rel_tol=0,abs_tol=1e-8)
        return a==b
    if not equal(actual,wanted):
        raise ValueError("Fixture geometry/layer/bounds mismatch")
    data=json.dumps(actual,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    return {"entity_count":len(actual),"geometry_sha256":hashlib.sha256(data).hexdigest(),
            "common_json_bytes":len(data)}

class Records:
    def __init__(self, directory):
        self.directory=Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True)
        self.path=self.directory/"cases.jsonl"
        if self.path.exists():
            raise FileExistsError("Use a new output directory; raw results are append-only")
    def add(self, kind, **values):
        row=dict(recorded_at_unix=time.time(),kind=kind,**values)
        with self.path.open("a",encoding="utf-8") as out:
            out.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+"\n")
        return row
    def json(self, name, data):
        path=self.directory/name
        temp=path.with_suffix(path.suffix+".tmp")
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
        temp.replace(path)

def summarize(rows):
    groups=defaultdict(list)
    for row in rows:
        if row["kind"]=="benchmark" and row["phase"]=="measured":
            groups[(row["scenario"],row["size"],row["backend"],row["mode"])].append(row)
    output=[]
    for (scenario,size,backend,mode), samples in sorted(groups.items()):
        good=[r["elapsed_ms"] for r in samples if r["ok"]]
        times=sorted(good)
        output.append(dict(scenario=scenario,size=size,backend=backend,mode=mode,
            samples=len(samples),passed=len(good),failed=len(samples)-len(good),
            median_ms=statistics.median(good) if good else None,
            p95_ms=times[math.ceil(.95*len(times))-1] if len(times)>=20 else None,
            max_ms=max(good) if good else None,
            failure_rate=(len(samples)-len(good))/len(samples)))
    return output

def write_summary(records):
    rows=[json.loads(s) for s in records.path.read_text(encoding="utf-8").splitlines()]
    summary=summarize(rows)
    if summary:
        with (records.directory/"summary.csv").open("w",newline="",encoding="utf-8") as out:
            writer=csv.DictWriter(out,fieldnames=list(summary[0]))
            writer.writeheader()
            writer.writerows(summary)
    return rows,summary
