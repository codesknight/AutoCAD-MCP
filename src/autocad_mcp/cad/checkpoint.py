"""Fail-closed checkpoint import. Only validated copies can become owned documents."""

import hashlib
import json
import math
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .capture import method, prop, retry_read
from .execution import invoke_mutator, native_action

VERSION = "autocad-checkpoint-snapshot/1"
COMMON = "Layer Color Linetype LinetypeScale Lineweight Visible".split()
FIELDS = {
    "AcDbLine": "StartPoint EndPoint Normal Thickness".split(),
    "AcDbCircle": "Center Radius Normal Thickness".split(),
    "AcDbArc": "Center Radius StartAngle EndAngle Normal Thickness".split(),
    "AcDbPolyline": "Coordinates Closed Normal Elevation ConstantWidth Thickness".split(),
    "AcDb2dPolyline": "Coordinates Closed Normal Elevation ConstantWidth Thickness Type".split(),
    "AcDbText": "TextString InsertionPoint TextAlignmentPoint Height ScaleFactor Rotation Normal Thickness ObliqueAngle Alignment StyleName Backward UpsideDown".split(),
}


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def plain(value):
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if type(value) is float and not math.isfinite(value):
        raise ValueError("NONFINITE_NATIVE_GEOMETRY")
    if type(value) not in (str, int, float, bool):
        raise ValueError("UNSUPPORTED_NATIVE_VALUE")
    return value


def snapshot(document):
    """Required native properties, no optional fields or bounding-box fallback."""
    space = prop(document, "ModelSpace")
    rows = []
    for index in range(prop(space, "Count")):
        entity = retry_read(lambda: method(space, "Item")(index))
        kind = prop(entity, "ObjectName")
        if kind not in FIELDS:
            raise ValueError("CHECKPOINT_UNSUPPORTED_ENTITY: " + kind)
        fields = {name: plain(prop(entity, name)) for name in COMMON + FIELDS[kind]}
        if kind == "AcDb2dPolyline" and fields["Type"] != 0:
            raise ValueError("CHECKPOINT_UNSUPPORTED_FITTED_POLYLINE")
        if kind in {"AcDbPolyline", "AcDb2dPolyline"}:
            count = len(fields["Coordinates"]) // (2 if kind == "AcDbPolyline" else 3)
            fields["Bulges"] = [
                plain(retry_read(lambda i=i: method(entity, "GetBulge")(i)))
                for i in range(count)
            ]
            fields["Widths"] = [
                retry_read(lambda i=i: widths(entity, i)) for i in range(count)
            ]
        rows.append(
            dict(
                object_id=str(prop(entity, "ObjectID")),
                handle=prop(entity, "Handle").upper(),
                type=kind,
                fields=fields,
            )
        )
    if prop(space, "Count") != len(rows):
        raise ValueError("CHECKPOINT_CHANGED_DURING_OBSERVATION")
    return dict(contract=VERSION, scope="model_space", entities=rows)


def widths(entity, index):
    ole = getattr(entity, "_oleobj_", None)
    if ole is None:
        return plain(entity.GetWidth(index))
    import pythoncom

    # Both width outputs are BYREF doubles, not optional GetWidth arguments.
    return plain(
        ole.InvokeTypes(
            ole.GetIDsOfNames("GetWidth"),
            0,
            pythoncom.DISPATCH_METHOD,
            (pythoncom.VT_VOID, 0),
            (
                (pythoncom.VT_I4, 1),
                (pythoncom.VT_R8 | pythoncom.VT_BYREF, 2),
                (pythoncom.VT_R8 | pythoncom.VT_BYREF, 2),
            ),
            index,
        )
    )


def validate_snapshot(value):
    if (
        set(value) != {"contract", "scope", "entities"}
        or value["contract"] != VERSION
        or value["scope"] != "model_space"
    ):
        raise ValueError("CHECKPOINT_SNAPSHOT_CONTRACT")
    handles, ids = set(), set()
    if not isinstance(value["entities"], list) or len(value["entities"]) > 100000:
        raise ValueError("CHECKPOINT_ENTITY_LIMIT")
    for row in value["entities"]:
        if (
            set(row) != {"object_id", "handle", "type", "fields"}
            or row["type"] not in FIELDS
        ):
            raise ValueError("CHECKPOINT_UNSUPPORTED_OR_INCOMPLETE_ENTITY")
        fields = set(COMMON + FIELDS[row["type"]])
        if row["type"] in {"AcDbPolyline", "AcDb2dPolyline"}:
            fields |= {"Bulges", "Widths"}
        if set(row["fields"]) != fields:
            raise ValueError("CHECKPOINT_INCOMPLETE_FIELDS")
        if row["type"] == "AcDb2dPolyline" and row["fields"]["Type"] != 0:
            raise ValueError("CHECKPOINT_UNSUPPORTED_FITTED_POLYLINE")
        if (
            not isinstance(row["handle"], str)
            or not re.fullmatch(r"[0-9A-F]+", row["handle"])
            or row["handle"] in handles
        ):
            raise ValueError("CHECKPOINT_AMBIGUOUS_HANDLE")
        if (
            not isinstance(row["object_id"], str)
            or not row["object_id"].isdigit()
            or row["object_id"] in ids
        ):
            raise ValueError("CHECKPOINT_AMBIGUOUS_OBJECT_ID")
        plain(list(row["fields"].values()))
        handles.add(row["handle"])
        ids.add(row["object_id"])
    canonical(value)


def match(expected, actual):
    validate_snapshot(expected)
    validate_snapshot(actual)
    old = {r["handle"]: r for r in expected["entities"]}
    new = {r["handle"]: r for r in actual["entities"]}
    if old.keys() != new.keys():
        raise ValueError("CHECKPOINT_ENTITY_SET_MISMATCH")
    mapping = []
    for handle, row in old.items():
        other = new[handle]
        if canonical([row["type"], row["fields"]]) != canonical(
            [other["type"], other["fields"]]
        ):
            raise ValueError("CHECKPOINT_NATIVE_FIELDS_MISMATCH: " + handle)
        mapping.append(
            dict(
                handle=handle,
                old_object_id=row["object_id"],
                new_object_id=other["object_id"],
                type=row["type"],
            )
        )
    return mapping


def require_dead(pid):
    import pywintypes
    import win32api
    import win32con
    import win32process

    if type(pid) is not int or pid <= 0:
        raise ValueError("CHECKPOINT_OWNER_PID_REQUIRED")
    try:
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, pid)
    except pywintypes.error as error:
        if error.winerror == 87:  # ERROR_INVALID_PARAMETER: PID absent.
            return
        raise ValueError("CHECKPOINT_OWNER_STATE_UNAVAILABLE") from error
    try:
        if win32process.GetExitCodeProcess(handle) == 259:
            raise ValueError("CHECKPOINT_OWNER_STILL_RUNNING")
    finally:
        handle.Close()


@contextmanager
def locked_read(path):
    """Windows share-read only: keep source immutable through copy/open/verification."""
    import win32con
    import win32file

    handle = win32file.CreateFile(
        str(path),
        win32con.GENERIC_READ,
        win32con.FILE_SHARE_READ,
        None,
        win32con.OPEN_EXISTING,
        0x00200000,
        None,
    )
    try:
        yield
    finally:
        handle.Close()


def fork(service, grant_id):
    from .com_artifacts import fingerprint, validated_directory

    # The grant directory is a LOCAL OPERATOR trust boundary, never an MCP argument.
    configured = os.environ.get("AUTOCAD_MCP_CHECKPOINT_GRANTS")
    if not configured or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", grant_id):
        raise ValueError("CHECKPOINT_RECOVERY_NOT_CONFIGURED")
    grants = validated_directory(configured)
    grant_path = grants / (grant_id + ".json")
    if (
        grant_path.is_symlink()
        or not grant_path.is_file()
        or grant_path.stat().st_file_attributes & 1024
    ):
        raise ValueError("CHECKPOINT_GRANT_NOT_REGULAR")
    with locked_read(grant_path):
        grant = json.loads(grant_path.read_text(encoding="utf-8"))
        if (
            grant["contract"] != "autocad-checkpoint-grant/1"
            or grant["unresolved_requests"] != []
        ):
            raise ValueError("CHECKPOINT_UNRESOLVED_WRITES")
        # Cross-process unknowns cannot be inferred from a missing local journal.
        if not grant.get("reviewed_execution_evidence_sha256") or not grant.get(
            "authorized_by"
        ):
            raise ValueError("CHECKPOINT_REVIEW_REQUIRED")
        evidence = Path(grant["execution_evidence_path"])
        validated_directory(str(evidence.parent))
        if (
            not evidence.is_absolute()
            or evidence.is_symlink()
            or evidence.stat().st_file_attributes & 1024
        ):
            raise ValueError("CHECKPOINT_EVIDENCE_NOT_REGULAR")
        if (
            hashlib.sha256(evidence.read_bytes()).hexdigest()
            != grant["reviewed_execution_evidence_sha256"]
        ):
            raise ValueError("CHECKPOINT_EXECUTION_EVIDENCE_CHANGED")
        for key in ("writer_pid", "cad_pid"):
            require_dead(grant[key])
        source = Path(grant["source_path"])
        allowed = validated_directory(grant["source_root"])
        validated_directory(str(source.parent))
        if (
            not source.is_absolute()
            or not source.resolve().is_relative_to(allowed)
            or source.suffix.lower() != ".dwg"
        ):
            raise ValueError("CHECKPOINT_SOURCE_NOT_ALLOWED")
        root = validated_directory(grant["output_directory"])
        frozen = grant["snapshot"]
        validate_snapshot(frozen)
        if digest(frozen) != grant["snapshot_sha256"]:
            raise ValueError("CHECKPOINT_SNAPSHOT_HASH_MISMATCH")
        if grant["old_instance_id"] == service.connection.instance_id:
            raise ValueError("CHECKPOINT_NEW_INSTANCE_REQUIRED")
        if not grant["old_instance_id"] or not grant["old_document_id"]:
            raise ValueError("CHECKPOINT_OLD_IDENTITY_REQUIRED")
        rows, before = service.connection.document_snapshot()
        if rows:  # Dedicated empty CAD only; no user drawing can be auto-closed or retargeted.
            raise ValueError("CHECKPOINT_EMPTY_INSTANCE_REQUIRED")
        import pythoncom

        deadline = time.monotonic() + service.connection.config.connect_timeout
        while True:
            try:
                if prop(
                    method(service.connection.app, "GetAcadState")(), "IsQuiescent"
                ):
                    break
            except (AttributeError, pythoncom.com_error):
                pass
            if time.monotonic() >= deadline:
                raise ValueError("CHECKPOINT_CAD_NOT_READY")
            pythoncom.PumpWaitingMessages()
            time.sleep(0.1)
        expected = dict(
            sha256=grant["source_sha256"], byte_size=grant["source_byte_size"]
        )
        with locked_read(source):
            if fingerprint(source) != expected:
                raise ValueError("CHECKPOINT_SOURCE_HASH_MISMATCH")
            # Durable one-use grant reservation survives loss of the Python journal.
            # Never remove it, even on failed/unknown copy or Open.
            claim = grants / (grant_id + ".claim")
            service.progress = dict(
                operation="fork_checkpoint",
                state="grant_reserving",
                grant_id=grant_id,
                grant_sha256=digest(grant),
                claim_path=str(claim),
            )

            def reserve():
                with claim.open("x", encoding="utf-8") as stream:
                    json.dump(
                        dict(
                            grant_sha256=digest(grant),
                            new_instance_id=service.connection.instance_id,
                            request_id=service.request_id,
                        ),
                        stream,
                    )
                    stream.flush()
                    os.fsync(stream.fileno())

            if claim.exists():
                raise ValueError(
                    "CHECKPOINT_GRANT_ALREADY_RESERVED: reconcile original request; never replay"
                )
            native_action("checkpoint.reserve", reserve)
            folder = root / ("checkpoint-" + uuid4().hex)
            service.progress.update(state="copy_prepared", path=str(folder))
            # Lifecycle/file side effect must be traced even before native Open.
            native_action("checkpoint.mkdir", lambda: folder.mkdir())
            target = folder / ("working-" + uuid4().hex + ".dwg")

            def copy():
                with source.open("rb") as read, target.open("xb") as write:
                    for block in iter(lambda: read.read(1048576), b""):
                        write.write(block)

            native_action("checkpoint.copy", copy)
            service.progress.update(state="copied_unverified", path=str(target))
            if fingerprint(target) != expected:
                raise ValueError("CHECKPOINT_COPY_HASH_MISMATCH")
            service.progress["state"] = "open_dispatched"
            invoke_mutator(service.connection.app.Documents, "Open", str(target), False)
            service.progress["state"] = "opened_unverified"
            rows, after = service.connection.document_snapshot()
            if len(rows) != 1 or len(after - before) != 1:
                raise ValueError("CHECKPOINT_OPEN_IDENTITY_MISMATCH")
            doc = rows[0]
            identity = service.connection.document_id(doc)
            service.progress["unverified_document_id"] = identity
            if (
                identity == grant["old_document_id"]
                or prop(doc, "ReadOnly")
                or os.path.normcase(prop(doc, "FullName"))
                != os.path.normcase(str(target))
                or service.connection.document_id(
                    prop(service.connection.app, "ActiveDocument")
                )
                != identity
            ):
                raise ValueError("CHECKPOINT_OPEN_BINDING_MISMATCH")
            service.progress["state"] = "mapping_native_fields"
            actual = snapshot(doc)
            mapping = match(frozen, actual)
            # Re-read rather than treating a single COM scan as a database transaction.
            if (
                digest(snapshot(doc)) != digest(actual)
                or fingerprint(source) != expected
                or fingerprint(target) != expected
                or not prop(doc, "Saved")
            ):
                raise ValueError("CHECKPOINT_CHANGED_DURING_VERIFICATION")
            for key in ("writer_pid", "cad_pid"):
                require_dead(grant[key])
            # Only the verified production path can grant ownership.
            space = prop(doc, "ModelSpace")
            service.connection.document = doc
            service.connection.model_space = space
            service.connection._owned_ids.add(identity)
            service.roots[identity] = str(root)
            service.progress["state"] = "verified_working_copy"
            return dict(
                contract="autocad-checkpoint-fork/1",
                **service.connection.binding(),
                source=dict(path=str(source), **expected),
                working=dict(path=str(target), **expected),
                snapshot_sha256=grant["snapshot_sha256"],
                actual_snapshot_sha256=digest(actual),
                mapping=mapping,
                mapping_sha256=digest(mapping),
                mapping_complete=True,
                quality_accepted=False,
                old_instance_id=grant["old_instance_id"],
                old_document_id=grant["old_document_id"],
                grant_sha256=digest(grant),
            )
