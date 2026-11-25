"""Explicit attachment to the opt-in NativeTests fixture, never production discovery."""
import time
from concurrent.futures import ThreadPoolExecutor

import pythoncom
import pywintypes
import win32com.client
import win32event
import win32process

from autocad_mcp.cad.capture import method, prop


def application(pid):
    moniker=pythoncom.CreateItemMoniker("!",f"AutoCADMCP-NativeTests-{pid}")
    obj=pythoncom.GetRunningObjectTable().GetObject(moniker).QueryInterface(pythoncom.IID_IDispatch)
    app=win32com.client.Dispatch(obj)
    if win32process.GetWindowThreadProcessId(prop(app,"HWND"))[1]!=pid:
        raise RuntimeError("Native fixture target PID differs")
    return app


class Busy:
    def __init__(self,pid):self.pid=pid
    def __enter__(self):
        def run():
            pythoncom.CoInitialize()
            try:
                app=application(self.pid)
                method(prop(app,"ActiveDocument"),"SendCommand")("CAD09_BUSY5\n")
            finally:pythoncom.CoUninitialize()
        self.pool=ThreadPoolExecutor(max_workers=1)
        self.future=self.pool.submit(run)
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            if self.future.done():
                self.future.result()
                raise RuntimeError("Busy fixture did not enter")
            try:event=win32event.OpenEvent(0x100000,False,f"Local\\AutoCADMCP-CAD09-{self.pid}")
            except (OSError,pywintypes.error):
                time.sleep(.05);continue
            try:
                if win32event.WaitForSingleObject(event,0)==win32event.WAIT_OBJECT_0:return self
            finally:event.Close()
            time.sleep(.05)
        raise TimeoutError("Native busy fixture not signalled")
    def __exit__(self,*unused):
        try:self.future.result(timeout=12)
        finally:self.pool.shutdown(wait=True)
