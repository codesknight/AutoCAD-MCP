"""COM connection management for AutoCAD.

Tries to attach to a running AutoCAD instance first (GetActiveObject),
falling back to launching a new one (Dispatch) if none is running.
"""
import time
import traceback
from uuid import uuid4

import pythoncom
import win32com.client

from autocad_mcp.config import Config, load_config


class CADConnectionError(RuntimeError):
    pass


class CADDocumentChangedError(CADConnectionError):
    """The active document no longer matches the bound COM document."""


class CADNewDocumentError(CADConnectionError):
    """Evidence from the native creation boundary, not an error-text guess."""

    def __init__(self, stage, invoked, acknowledged, before, cause):
        super().__init__(f"New document failed at {stage}: {cause}")
        self.evidence = {
            "contract": "autocad-native-create/1", "operation": "new_document",
            "stage": stage, "native_invoked": invoked,
            "native_acknowledged": acknowledged, "implicit_creates": 0,
            "before_documents": before,
            "exception": {"type": type(cause).__name__, "message": str(cause),
                          "hresult": getattr(cause, "hresult", None),
                          "traceback": traceback.format_exc()},
        }


class CADConnection:
    def __init__(self, config: Config | None = None):
        self.config = config or load_config()
        self.app = None
        self.document = None
        self.model_space = None
        self.instance_id = uuid4().hex
        self._identities = []
        self._owned_ids = set()

    @staticmethod
    def _native_identity(document):
        ole = getattr(document, "_oleobj_", None)
        # COM identity is canonical IUnknown, never name/path/ObjectID.
        return ole.QueryInterface(pythoncom.IID_IUnknown) if ole is not None else document

    @staticmethod
    def _same(left, right):
        if hasattr(left, "QueryInterface") and hasattr(right, "QueryInterface"):
            return left == right
        return left is right  # Offline plain-object fixtures only.

    def document_id(self, document):
        token = self._native_identity(document)
        for known, identity in self._identities:
            if self._same(token, known):
                return identity
        identity = uuid4().hex
        self._identities.append((token, identity))
        return identity

    def document_snapshot(self):
        # Reuse the authoritative, bounded read helpers. A wrapper returned
        # just after Open may have a stale Python Count/Item method map even
        # though the native collection is ready. These are reads, not Open.
        from autocad_mcp.cad.capture import method, prop, retry_read
        documents = prop(self.app, "Documents")
        rows = [retry_read(lambda i=i: method(documents, "Item")(i))
                for i in range(prop(documents, "Count"))]
        identities = {self.document_id(doc) for doc in rows}
        self._identities = [(token, key) for token, key in self._identities if key in identities]
        self._owned_ids.intersection_update(identities)
        return rows, identities

    def binding(self):
        self.ensure_document()
        from autocad_mcp.cad.capture import prop
        identity = self.document_id(self.document)
        return dict(instance_id=self.instance_id, document_id=identity,
                    name=prop(self.document, "Name"), revision=None, revision_mode="unsupported",
                    managed=identity in self._owned_ids, read_only=bool(prop(self.document, "ReadOnly")))

    def connect(self, *, allow_launch=True) -> None:
        prog_ids = [self.config.prog_id, *self.config.prog_id_fallbacks]
        last_error: Exception | None = None

        for prog_id in prog_ids:
            try:
                self.app = win32com.client.GetActiveObject(prog_id)
                break
            except Exception as exc:  # noqa: BLE001 - COM raises plain Exception/pywintypes.com_error
                last_error = exc
                continue

        if self.app is None and allow_launch:
            for prog_id in prog_ids:
                try:
                    self.app = win32com.client.Dispatch(prog_id)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    continue

        if self.app is None:
            raise CADConnectionError(
                f"无法连接到 AutoCAD(尝试过的 ProgID: {prog_ids})。"
                f"请确认 AutoCAD 已安装且 ProgID 配置正确。原始错误: {last_error}"
            )

        if allow_launch:
            self.app.Visible = self.config.visible
        if self.app.Documents.Count == 0:
            # Attaching must not create a drawing before the explicit request.
            self.document = self.model_space = None
        else:
            self._wait_for_document(self.config.connect_timeout)

    def _wait_for_document(self, timeout: int, excluded_names=None, excluded_ids=None) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                document = self.app.ActiveDocument
                model_space = document.ModelSpace
                if excluded_ids is not None:
                    _, ids = self.document_snapshot()
                    if (len(ids) != len(excluded_ids)+1 or not excluded_ids.issubset(ids)
                            or self.document_id(document) not in ids-excluded_ids):
                        pythoncom.PumpWaitingMessages()
                        time.sleep(0.1)
                        continue
                elif excluded_names is not None:
                    docs = self.app.Documents
                    names = {docs.Item(i).Name for i in range(docs.Count)}
                    if (len(names) != len(excluded_names) + 1
                            or not excluded_names.issubset(names)
                            or document.Name not in names - excluded_names):
                        pythoncom.PumpWaitingMessages()
                        time.sleep(0.1)
                        continue
                self.document, self.model_space = document, model_space
                return
            except (pythoncom.com_error, AttributeError):
                # A freshly created document's COM object isn't always ready
                # for attribute access immediately (dynamic dispatch can
                # return a not-yet-resolved "<unknown>" wrapper) — retry.
                time.sleep(0.5)
        raise CADConnectionError("等待 AutoCAD 文档就绪超时")

    def new_document(self, template: str | None = None) -> None:
        """Create a brand-new drawing and switch to it, instead of reusing
        whatever document happened to be active when we connected.

        The direct return value of Documents.Add() is an unreliable COM
        reference under pywin32's dynamic dispatch, so we re-fetch via
        ActiveDocument (with retry via _wait_for_document) instead of
        trusting the return value.
        """
        invoked = acknowledged = False
        before = None
        stage = "preflight"
        try:
            deadline = time.monotonic() + self.config.connect_timeout
            while True:
                try:
                    documents = self.app.Documents
                    before = {documents.Item(i).Name for i in range(documents.Count)}
                    _, before_ids = self.document_snapshot()
                    # Resolve metadata without invoking Add. Dynamic wrappers can
                    # lose their method map; use IDispatch's authoritative DISPID.
                    ole = getattr(documents, "_oleobj_", None)
                    if ole is not None:
                        dispid = ole.GetIDsOfNames("Add")
                        invoke = ole.Invoke
                        add = lambda *args: invoke(dispid, 0, pythoncom.DISPATCH_METHOD, True, *args)
                    else:
                        add = documents.Add  # Plain objects in offline tests.
                    if not callable(add):
                        raise AttributeError("Documents.Add is not callable")
                    break
                except (pythoncom.com_error, AttributeError):
                    if time.monotonic() >= deadline:
                        raise
                    pythoncom.PumpWaitingMessages()
                    time.sleep(0.1)
            self.document = self.model_space = None
            stage = "native_call"
            invoked = True  # Any failure beyond this point is conservatively unknown.
            from autocad_mcp.cad.execution import native_action
            native_action("Documents.Add", lambda: add(template) if template else add())
            acknowledged = True
            stage = "binding"
            self._wait_for_document(self.config.connect_timeout, excluded_names=before, excluded_ids=before_ids)
            self._owned_ids.add(self.document_id(self.document))
        except Exception as exc:
            raise CADNewDocumentError(stage, invoked, acknowledged,
                                      sorted(before) if before is not None else None, exc) from exc

    def ensure_document(self) -> None:
        """Fail on a switched/closed document rather than silently retargeting.

        Canonical COM identity is stable across SaveAs, distinct for same-name
        documents, and retired when closed. Reconnection creates fresh IDs.
        COM failures propagate; writes are never replayed after reconnecting.
        """
        if self.document is None or self.app is None:
            raise CADConnectionError("CAD document is not connected")
        from autocad_mcp.cad.capture import prop
        bound = self.document_id(self.document)
        active = self.document_id(prop(self.app, "ActiveDocument"))
        if bound != active:
            raise CADDocumentChangedError(
                "AutoCAD active document changed; call new_drawing for a new scratch "
                "document or explicitly close/recreate the backend to select the active document"
            )
        if getattr(self.app, "_oleobj_", None) is not None or hasattr(self.app, "Documents"):
            _, ids = self.document_snapshot()
            if bound not in ids:
                raise CADDocumentChangedError("Bound document was closed; no automatic rebinding")

    def disconnect(self) -> None:
        """Release references only; never save, close drawings, or quit AutoCAD."""
        self.model_space = None
        self.document = None
        self.app = None
        self._identities.clear()
        self._owned_ids.clear()

    def is_connected(self) -> bool:
        if self.app is None:
            return False
        try:
            _ = self.app.Visible
            return True
        except pythoncom.com_error:
            return False


if __name__ == "__main__":
    conn = CADConnection()
    conn.connect()
    print("Connected:", conn.is_connected())
    print("Active document:", conn.document.Name)
