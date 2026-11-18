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
