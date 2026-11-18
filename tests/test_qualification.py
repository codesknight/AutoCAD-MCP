"""Meaningful checks for benchmark correctness and evidence, without starting CAD."""
import math
import pytest
from benchmarks.common import Records,expected,fixture,geometry_check,summarize

def rows(count=3):
    result=expected(count)
    for i,row in enumerate(result):
        row.update(object_id=987+i,handle=str(i+1))
    return result

def test_geometry_validation_is_identity_independent_but_requires_all_geometry():
    assert geometry_check(rows(),3)==geometry_check(list(reversed(rows())),3)
    for mutate in (
        lambda r:r[0].update(layer="wrong"),
        lambda r:r[0]["start_point"].__setitem__(0,1),
        lambda r:r[0]["bounding_box"]["max"].__setitem__(1,99),
        lambda r:r.pop(),
    ):
        data=rows()
        mutate(data)
        with pytest.raises(ValueError):
            geometry_check(data,3)

def test_query_evidence_rejects_nonfinite_or_unsupported_geometry():
    for value in (math.nan,math.inf,-math.inf):
        data=rows()
        data[0]["start_point"][0]=value
        with pytest.raises(ValueError):
            geometry_check(data,3)
    data=rows()
    data[0]["type"]="AcDbCircle"
    with pytest.raises(ValueError):
        geometry_check(data,3)

def test_fixture_and_validation_share_the_declared_units_and_bounds():
    line=fixture(51)[50]
    assert line["start"]==[0,3,0] and line["end"]==[1,5,0]
    assert expected(51)[1]["layer"]=="CAD09_FIXTURE"

def test_summary_retains_failures_excludes_warmup_and_does_not_invent_small_sample_p95():
    data=[dict(kind="benchmark",phase="measured",scenario="query",size=100,
        backend="http",mode="single",ok=True,elapsed_ms=i) for i in range(20)]
    data.append(dict(data[0],phase="warmup",elapsed_ms=9999))
    data.append(dict(data[0],ok=False,elapsed_ms=10000))
    result=summarize(data)[0]
    assert result["samples"]==21 and result["failed"]==1 and result["p95_ms"]==18
    assert result["median_ms"]==9.5
    assert summarize(data[:5])[0]["p95_ms"] is None

def test_raw_records_are_append_only_and_json_rejects_nan(tmp_path):
    records=Records(tmp_path)
    records.add("failed_case",ok=False)
    with pytest.raises(FileExistsError):
        Records(tmp_path)
    before=records.path.read_bytes()
    with pytest.raises(ValueError):
        records.add("bad",elapsed_ms=math.nan)
    assert records.path.read_bytes()==before

def test_cleanup_activates_only_owned_scratch_before_cancelling_commands(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import sys
    from benchmarks.native import Native
    events=[]
    class Document:
        def __init__(self,name):
            self.Name=name
    class Documents(list):
        @property
        def Count(self):
            return len(self)
        def Item(self,name):
            if isinstance(name,int):
                return self[name]
            return next(d for d in self if d.Name==name)
    class App:
        def __init__(self):
            self.Documents=Documents([Document("user.dwg"),Document("scratch.dwg")])
            self.ActiveDocument=self.Documents[0]
        def Quit(self):
            raise AssertionError("User-owned CAD must not be quit")
        def GetAcadState(self):
            return SimpleNamespace(IsQuiescent=True)
    native=Native.__new__(Native)
    native.app=App()
    native.owned={"scratch.dwg"}
    native.original_active="user.dwg"
    native.original_names=["user.dwg"]
    native.owned_pid=None
    native.pid=123
    native.running=True
    native.settings_written=False
    native.old_token="original-token"
    native.raw=SimpleNamespace(close=lambda:events.append("client_closed"))
    native.records=Records(tmp_path)
    def check_context():
        assert native.app.ActiveDocument.Name=="scratch.dwg"
        events.append("safe_context")
    native.idle=check_context
    native.stop=check_context
    def close(name):
        assert name=="scratch.dwg"
        native.app.Documents.remove(native.app.Documents.Item(name))
        native.owned.remove(name)
    native.close_document=close
    monkeypatch.setitem(sys.modules,"pythoncom",SimpleNamespace(CoUninitialize=lambda:None))
    monkeypatch.setenv("AUTOCAD_BRIDGE_TOKEN","test-token")
    result=native.close()
    assert result["listener_stopped"] and result["remaining_documents"]==[]
    assert result["original_active_restored"] and not result["cad_process_closed"]
    assert native.app.ActiveDocument.Name=="user.dwg"
    assert events==["safe_context","safe_context","client_closed"]

def test_report_preserves_failures_and_requires_completed_cleanup_for_acceptance(tmp_path):
    import json
    from benchmarks.report import render
    root=tmp_path/"2026-11-19"
    run=Records(root/"fault-01")
    run.json("plan.json",{"mode":"faults"})
    run.add("fault",case="problem",status="failed")
    cases=[dict(case="problem",status="failed",error_type="AssertionError"),
           dict(case="cad_process_restart",status="not_run",reason="preserve original")]
    run.json("faults.json",{"completed":True,"cases":cases})
    run.json("qualification.json",{"completed":False})
    report=tmp_path/"report.md"
    render(root,report)
    assert "尚无完整且完成清理的故障运行" in report.read_text(encoding="utf-8")
    run.json("qualification.json",{"completed":True})
    render(root,report)
    assert "失败 1 项，未执行 1 项" in report.read_text(encoding="utf-8")
    restart=Records(root/"restart-01")
    restart.json("plan.json",{"mode":"cad_restart"})
    restart.add("restart",status="passed")
    restart.json("restart.json",{"completed":True,"passed":True})
    restart.json("qualification.json",{"completed":True})
    render(root,report)
    text=report.read_text(encoding="utf-8")
    assert "通过 1 项，失败 1 项，未执行 0 项" in text
    assert json.loads((root/"fault-01/faults.json").read_text(encoding="utf-8"))["cases"][1]["status"]=="not_run"
