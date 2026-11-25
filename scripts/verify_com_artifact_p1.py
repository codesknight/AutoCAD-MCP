"""Opt-in artifact API regression using accepted house/circuit DWGs, no models.

Imports copies into new owned working documents; exercises production receipts,
save/reopen and independent native readback. Never attaches to an existing PID.
"""

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

import pythoncom
import win32com.client
import win32process

from autocad_mcp.cad.backends.com_backend import COMBackend, COMSession
from autocad_mcp.cad.capture import method, prop
from autocad_mcp.cad.com_artifacts import COMArtifacts
from autocad_mcp.cad.connection import CADConnection
from autocad_mcp.cad.controller import CADController
from autocad_mcp.cad.geometry import to_variant_point
from autocad_mcp.cad.query import CADQuery
from autocad_mcp.config import load_config


def snapshot(doc):
    rows = []
    space = prop(doc, "ModelSpace")
    for i in range(prop(space, "Count")):
        e = method(space, "Item")(i)
        row = dict(
            type=prop(e, "ObjectName"), layer=prop(e, "Layer"), color=prop(e, "Color")
        )
        for name in [
            "StartPoint",
            "EndPoint",
            "Center",
            "Radius",
            "Coordinates",
            "Closed",
            "TextString",
            "InsertionPoint",
            "Height",
            "Rotation",
            "Area",
            "PatternName",
            "NumberOfLoops",
        ]:
            try:
                e._oleobj_.GetIDsOfNames(
                    name
                )  # Unsupported names must not enter read-retry loops.
                value = prop(e, name)
            except (AttributeError, pythoncom.com_error):
                continue
            row[name] = list(value) if isinstance(value, tuple) else value
        rows.append(row)

    def rounded(value):
        if type(value) is float:
            return round(value, 7)
        if isinstance(value, list):
            return [rounded(x) for x in value]
        if isinstance(value, dict):
            return {k: rounded(v) for k, v in value.items()}
        return value

    return sorted(
        json.dumps(rounded(r), sort_keys=True, ensure_ascii=False) for r in rows
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cader-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    existing = set(
        json.loads(
            subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "ConvertTo-Json -InputObject @((Get-Process acad -ErrorAction SilentlyContinue).Id)",
                ],
                text=True,
            )
        )
    )
    report = dict(passed=False, existing_pids=sorted(existing), cases=[], cleanup=False)

    def persist():
        (out / "qualification.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    persist()

    class Session(COMSession):
        def __init__(self, cfg):
            self.connection = CADConnection(cfg)
            self.connection.app = win32com.client.DispatchEx(cfg.prog_id)
            app = self.connection.app
            pid = win32process.GetWindowThreadProcessId(prop(app, "HWND"))[1]
            if pid in existing:
                raise RuntimeError(
                    "DispatchEx reused an existing CAD; no modifications allowed"
                )
            report["owned_pid"] = pid
            persist()
            docs = prop(app, "Documents")
            for i in reversed(range(prop(docs, "Count"))):
                initial = method(docs, "Item")(i)
                if prop(initial, "FullName") or prop(
                    prop(initial, "ModelSpace"), "Count"
                ):
                    raise RuntimeError(
                        "Unexpected populated startup document; refusing test"
                    )
                method(initial, "Close")(False)
            pythoncom.PumpWaitingMessages()
            time.sleep(0.5)
            self.controller = CADController(self.connection)
            self.query = CADQuery(self.connection)
            self.files = COMArtifacts(self.connection)

        def execute(self, operation, payload):
            if operation == "analyze_reference_drawing":
                # Test-only import/readback hook; absent from the production backend.
                if payload["file_path"] == "snapshot":
                    return snapshot(self.connection.document)
                if payload["file_path"] == "verification":
                    doc = self.files.verifications[payload["entity_type"]][0]
                    return snapshot(doc)
                block = method(self.connection.document.ModelSpace, "InsertBlock")(
                    to_variant_point(0, 0, 0), payload["file_path"], 1.0, 1.0, 1.0, 0.0
                )
                method(block, "Explode")()
                method(block, "Delete")()
                return snapshot(self.connection.document)
            return super().execute(operation, payload)

        def close(self):
            app = self.connection.app
            try:
                docs = prop(app, "Documents")
                for i in range(prop(docs, "Count")):
                    path = prop(method(docs, "Item")(i), "FullName")
                    if path and not Path(path).resolve().is_relative_to(out):
                        raise RuntimeError(
                            "Unexpected document in owned test instance; refusing cleanup"
                        )
                for i in reversed(range(prop(docs, "Count"))):
                    method(method(docs, "Item")(i), "Close")(False)
                    pythoncom.PumpWaitingMessages()
                    time.sleep(0.25)
                for _ in range(40):
                    if prop(method(app, "GetAcadState")(), "IsQuiescent"):
                        break
                    pythoncom.PumpWaitingMessages()
                    time.sleep(0.1)
                method(app, "Quit")()
                report["cleanup"] = True
                persist()
            finally:
                super().close()

    backend = COMBackend(load_config(), session_factory=Session)
    from uuid import uuid4

    calls = []

    def call(op, values, doc=None):
        result = backend.execute_evidenced(
            op,
            values,
            request_id=uuid4().hex,
            instance_id=backend.instance_id,
            document_id=doc,
        )
        calls.append(result)
        (out / "calls.json").write_text(
            json.dumps(calls, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert result["receipt"]["status"] == "succeeded", result
        return result["result"]

    try:
        summary = json.loads(
            (
                args.cader_root
                / "docs/validation/evidence/2026-11-25-p0-quality-summary.json"
            ).read_text(encoding="utf-8")
        )
        for case in summary["cases"][1:]:
            run = args.cader_root / ".cader/runs" / case["run"]
            q = next(
                json.loads(p.read_text(encoding="utf-8-sig"))
                for p in run.rglob("quality.json")
                if hashlib.sha256(p.read_bytes()).hexdigest()
                == case["evidence_sha256"]["quality"]
            )
            source = Path((q.get("artifact") or q["execution"]["artifact"])["path"])
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            assert digest == case["artifact_sha256"]
            call("new_document", {})
            binding = backend.document_binding()
            doc = binding["document_id"]
            before = backend.execute(
                "analyze_reference_drawing", dict(file_path=str(source))
            )
            assert len(before) == case["native_entities"]
            artifact = call(
                "save_document_artifact",
                dict(output_directory=str(out), file_name=case["case"] + ".dwg"),
                doc,
            )
            assert (
                hashlib.sha256(Path(artifact["path"]).read_bytes()).hexdigest()
                == artifact["sha256"]
            )
            verification = call(
                "reopen_document_artifact",
                dict(artifact_id=artifact["artifact_id"]),
                doc,
            )
            assert verification["document_id"] != doc and verification["read_only"]
            query = call(
                "query_verification_entities",
                dict(document_id=verification["document_id"]),
                verification["document_id"],
            )
            assert len(query["items"]) == len(before)
            after = backend.execute(
                "analyze_reference_drawing",
                dict(file_path="verification", entity_type=verification["document_id"]),
            )
            assert before == after and backend.document_binding()["document_id"] == doc
            assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
            report["cases"].append(
                dict(
                    case=case["case"],
                    entities=len(before),
                    native_geometry_matches=True,
                    original_file_unchanged=True,
                    artifact=artifact,
                    verification=verification,
                )
            )
            persist()
        report["passed"] = True
    except Exception as error:
        report["error"] = dict(type=type(error).__name__, message=str(error))
        raise
    finally:
        backend.close()
        persist()
    print(
        json.dumps(
            dict(
                passed=report["passed"],
                cleanup=report["cleanup"],
                cases=len(report["cases"]),
            )
        )
    )


if __name__ == "__main__":
    main()
