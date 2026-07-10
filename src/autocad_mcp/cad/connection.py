"""COM connection management for AutoCAD.

Tries to attach to a running AutoCAD instance first (GetActiveObject),
falling back to launching a new one (Dispatch) if none is running.
"""
import time

import pythoncom
import win32com.client

from autocad_mcp.config import Config, load_config


class CADConnectionError(RuntimeError):
    pass


class CADConnection:
    def __init__(self, config: Config | None = None):
        self.config = config or load_config()
        self.app = None
        self.document = None
        self.model_space = None

    def connect(self) -> None:
        prog_ids = [self.config.prog_id, *self.config.prog_id_fallbacks]
        last_error: Exception | None = None

        for prog_id in prog_ids:
            try:
                self.app = win32com.client.GetActiveObject(prog_id)
                break
            except Exception as exc:  # noqa: BLE001 - COM raises plain Exception/pywintypes.com_error
                last_error = exc
                continue

        if self.app is None:
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

        self.app.Visible = self.config.visible
        if self.app.Documents.Count == 0:
            self.new_document()
        else:
            self._wait_for_document(self.config.connect_timeout)

    def _wait_for_document(self, timeout: int) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.document = self.app.ActiveDocument
                self.model_space = self.document.ModelSpace
                return
            except pythoncom.com_error:
                time.sleep(0.5)
        raise CADConnectionError("等待 AutoCAD 文档就绪超时")

    def new_document(self, template: str | None = None) -> None:
        """Create a brand-new drawing and switch to it, instead of reusing
        whatever document happened to be active when we connected."""
        doc = self.app.Documents.Add(template) if template else self.app.Documents.Add()
        doc.Activate()
        self.document = doc
        self.model_space = doc.ModelSpace

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
