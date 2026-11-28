"""COM artifact lifecycle on the owning STA; file work is not a CAD transaction."""

import hashlib
import os
import re
import stat
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from .capture import prop
from .execution import invoke_mutator

OPERATIONS = frozenset(
    {
        "save_document_artifact",
        "reopen_document_artifact",
        "query_verification_entities",
        "fork_checkpoint",
        "get_checkpoint_snapshot",
    }
)


def validated_directory(value):
    if (
        not os.path.isabs(value)
        or value.startswith(("\\\\", "//"))
        or ".." in Path(value).parts
    ):
        raise ValueError(
            "OUTPUT_PATH_NOT_ALLOWED: canonical absolute local directory required"
        )
    path = Path(value).resolve(strict=True)
    if not path.is_dir():
        raise ValueError("OUTPUT_PATH_NOT_ALLOWED: existing directory required")
    for part in [Path(value), *Path(value).parents]:
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(
            info, "st_file_attributes", 0
        ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
            raise ValueError("OUTPUT_PATH_NOT_ALLOWED: reparse point")
    return path


def validated_filename(value):
    if (
        not re.fullmatch(r'[^<>:"/\\|?*\x00-\x1f]{1,180}\.[dD][wW][gG]', value)
        or value.endswith((" ", "."))
        or value.split(".")[0].upper()
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
    ):
        raise ValueError("OUTPUT_PATH_NOT_ALLOWED: plain DWG filename required")
    return value


def fingerprint(path):
    path = Path(path)
    validated_directory(str(path.parent))
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(
        info, "st_file_attributes", 0
    ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
        raise ValueError("ARTIFACT_INVALID: not a regular file")
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        header = stream.read(6)
        if not re.fullmatch(rb"AC10[0-9]{2}", header):
            raise ValueError("ARTIFACT_INVALID: DWG header")
        digest = hashlib.sha256(header)
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        after = os.fstat(stream.fileno())
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or after.st_size <= 6
    ):
        raise ValueError("ARTIFACT_CHANGED_DURING_READ")
    return dict(sha256=digest.hexdigest(), byte_size=after.st_size)


class COMArtifacts:
    def __init__(self, connection):
        self.connection = connection
        self.artifacts = {}
        self.roots = {}
        self.verifications = {}
        self.progress = None
        self.request_id = None

    def fork_checkpoint(self, grant_id: str):
        from .checkpoint import fork
        return fork(self, grant_id)

    def get_checkpoint_snapshot(self):
        from .checkpoint import digest, snapshot
        binding = self.connection.binding()
        if not binding["managed"] or not prop(self.connection.document, "Saved"):
            raise ValueError("CHECKPOINT_SAVED_MANAGED_DOCUMENT_REQUIRED")
        path = prop(self.connection.document, "FullName")
        source = fingerprint(path)
        frozen = snapshot(self.connection.document)
        if (snapshot(self.connection.document) != frozen or not prop(self.connection.document, "Saved")
                or fingerprint(path) != source or prop(self.connection.document, "FullName") != path):
            raise ValueError("CHECKPOINT_CHANGED_DURING_OBSERVATION")
        return dict(binding=binding, snapshot=frozen, snapshot_sha256=digest(frozen),
                    source=dict(path=path, **source))

    def save_document_artifact(self, output_directory: str, file_name: str):
        binding = self.connection.binding()
        if not binding["managed"] or binding["read_only"]:
            raise ValueError("WRITABLE_WORKING_DOCUMENT_REQUIRED")
        root = validated_directory(output_directory)
        name = validated_filename(file_name)
        key = binding["document_id"]
        if key in self.roots and os.path.normcase(str(root)) != os.path.normcase(
            self.roots[key]
        ):
            raise ValueError("OUTPUT_DIRECTORY_ALREADY_BOUND")
        if len(self.artifacts) >= 2048:
            raise ValueError("ARTIFACT_REGISTRY_FULL")
        artifact_id = uuid4().hex
        folder = root / ("artifact-" + artifact_id)
        folder.mkdir()  # Exclusive namespace; a collision is refused before SaveAs.
        path = folder / name
        self.roots[key] = str(root)
        self.progress = dict(
            operation="save_document_artifact",
            state="prepared",
            path=str(path),
            source_document_id=key,
        )
        if path.exists():
            raise ValueError("OUTPUT_EXISTS")
        invoke_mutator(self.connection.document, "SaveAs", str(path))
        self.progress["state"] = "native_acknowledged_unverified"
        if os.path.normcase(
            prop(self.connection.document, "FullName")
        ) != os.path.normcase(str(path)):
            raise ValueError("SAVED_DOCUMENT_PATH_MISMATCH")
        result = dict(
            contract="autocad-file-artifact/1",
            artifact_id=artifact_id,
            instance_id=binding["instance_id"],
            source_document_id=key,
            revision=None,
            revision_mode="unsupported",
            output_directory=str(root),
            path=str(path),
            **fingerprint(path),
            state="saved",
            saved_at=datetime.now(timezone.utc).isoformat(),
            save_semantics="save_as_renames_source",
            verification="not_performed",
        )
        self.artifacts[artifact_id] = result
        self.progress = {**self.progress, "state": "saved", "artifact_id": artifact_id}
        return deepcopy(result)

    def _artifact(self, artifact_id):
        if artifact_id not in self.artifacts:
            raise ValueError("ARTIFACT_NOT_AVAILABLE_IN_THIS_BACKEND")
        artifact = self.artifacts[artifact_id]
        actual = fingerprint(artifact["path"])
        if any(actual[k] != artifact[k] for k in actual):
            raise ValueError("ARTIFACT_TAMPERED")
        return artifact

    def reopen_document_artifact(self, artifact_id: str):
        artifact = self._artifact(artifact_id)
        source = self.connection.document
        if self.connection.document_id(source) != artifact["source_document_id"]:
            raise ValueError("ARTIFACT_SOURCE_DOCUMENT_MISMATCH")
        if len(self.verifications) >= 2048:
            raise ValueError("VERIFICATION_REGISTRY_FULL")
        rows, before = self.connection.document_snapshot()
        for other in rows:
            if self.connection.document_id(other) != artifact["source_document_id"]:
                if (
                    not prop(other, "FullName")
                    and prop(prop(other, "ModelSpace"), "Count") == 0
                ):
                    raise ValueError(
                        "OTHER_EMPTY_DOCUMENT_OPEN: close it explicitly before verification; AutoCAD may auto-close it"
                    )
        path = Path(artifact["path"])
        folder = path.parent / ("verification-" + uuid4().hex)
        folder.mkdir()
        # AutoCAD can resolve an already-open basename instead of loading a
        # same-name copy. Use a unique basename while keeping exact file bytes.
        copy = folder / ("verification-" + uuid4().hex + ".dwg")
        with path.open("rb") as read, copy.open("xb") as write:
            for block in iter(lambda: read.read(1024 * 1024), b""):
                write.write(block)
        if fingerprint(copy) != dict(
            sha256=artifact["sha256"], byte_size=artifact["byte_size"]
        ):
            raise ValueError("ARTIFACT_COPY_MISMATCH")
        self._artifact(artifact_id)
        self.progress = dict(
            operation="reopen_document_artifact",
            state="prepared",
            artifact_id=artifact_id,
            path=str(copy),
        )
        invoke_mutator(self.connection.app.Documents, "Open", str(copy), True)
        self.progress["state"] = "native_acknowledged_unverified"
        import pythoncom

        deadline = time.monotonic() + 5
        while True:
            rows, ids = self.connection.document_snapshot()
            created = ids - before
            self.progress["document_observation"] = dict(
                before=sorted(before),
                after=sorted(ids),
                documents=[
                    dict(
                        document_id=self.connection.document_id(d), name=prop(d, "Name")
                    )
                    for d in rows
                ],
            )
            if not before.issubset(ids) or len(created) > 1:
                raise ValueError("REOPEN_DOCUMENT_SET_MISMATCH")
            if len(created) == 1:
                break
            if time.monotonic() >= deadline:
                raise ValueError("REOPEN_DOCUMENT_NOT_OBSERVED")
            pythoncom.PumpWaitingMessages()
            time.sleep(0.1)
        doc = next(d for d in rows if self.connection.document_id(d) in created)
        identity = self.connection.document_id(doc)
        if not prop(doc, "ReadOnly") or os.path.normcase(
            prop(doc, "FullName")
        ) != os.path.normcase(str(copy)):
            raise ValueError("READONLY_REOPEN_BINDING_MISMATCH")
        result = dict(
            contract="autocad-verification-document/1",
            instance_id=self.connection.instance_id,
            document_id=identity,
            source_document_id=artifact["source_document_id"],
            source_artifact_id=artifact_id,
            managed=False,
            read_only=True,
            revision=None,
            revision_mode="unsupported",
            path=str(copy),
            sha256=artifact["sha256"],
            byte_size=artifact["byte_size"],
            verification="content_not_yet_compared",
        )
        self.verifications[identity] = (doc, result)
        self.progress = {
            **self.progress,
            "state": "readonly_opened",
            "document_id": identity,
            "verification_binding": result,
        }
        # Keep the legacy working binding. Only reactivate our original source.
        invoke_mutator(source, "Activate")
        self.connection.ensure_document()
        self.progress = {
            **self.progress,
            "state": "readonly_opened",
            "document_id": identity,
        }
        return deepcopy(result)

    def query_verification_entities(self, document_id: str):
        from .query import CADQuery

        if document_id not in self.verifications:
            raise ValueError("VERIFICATION_DOCUMENT_NOT_FOUND")
        doc, binding = self.verifications[document_id]
        _, ids = self.connection.document_snapshot()
        if (
            document_id not in ids
            or not prop(doc, "ReadOnly")
            or not prop(doc, "Saved")
            or os.path.normcase(prop(doc, "FullName"))
            != os.path.normcase(binding["path"])
        ):
            raise ValueError("VERIFICATION_DOCUMENT_INVALID")
        self._artifact(binding["source_artifact_id"])
        if fingerprint(binding["path"]) != dict(
            sha256=binding["sha256"], byte_size=binding["byte_size"]
        ):
            raise ValueError("VERIFICATION_COPY_TAMPERED")
        query = CADQuery(SimpleNamespace(document=doc))
        items = query.query_entities()
        if (
            not prop(doc, "Saved")
            or not prop(doc, "ReadOnly")
            or os.path.normcase(prop(doc, "FullName"))
            != os.path.normcase(binding["path"])
        ):
            raise ValueError("VERIFICATION_DOCUMENT_CHANGED_DURING_QUERY")
        return {
            **deepcopy(binding),
            "contract": "autocad-verification-query/1",
            "items": items,
            "geometry_scope": "legacy_summary_partial",
            "snapshot_revision": None,
        }
