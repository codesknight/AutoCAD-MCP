"""Foreground capture with bounded COM reads and a verified restoration receipt.

Only property reads / method resolution are retried. Native mutators and printing
are invoked once; a lost mutation acknowledgement is never reclassified as safe.
"""
import math
import os
import tempfile
import time
import traceback
from uuid import uuid4

import pythoncom
from win32com.client import VARIANT
from win32com.client.dynamic import DumbDispatch

from autocad_mcp.cad.geometry import to_variant_double_array, to_variant_point

FIELDS = ("ConfigName", "CanonicalMediaName", "PlotType", "PlotRotation",
          "UseStandardScale", "StandardScale", "CenterPlot", "PaperUnits", "PlotOrigin")


class CADCaptureError(RuntimeError):
    def __init__(self, evidence):
        self.evidence = evidence
        super().__init__(f"CAD_CAPTURE_FAILED: {evidence['stage']}; "
                         f"restored={evidence['restoration_verified']}; {evidence['error']}")


def plain(value):
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("CAD_CAPTURE_NONFINITE_STATE")
        return round(value, 9)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise TypeError("CAD_CAPTURE_NON_DATA_STATE")


def retry_read(action):
    for attempt in range(20):
        try:
            return action()
        except (AttributeError, pythoncom.com_error):
            if attempt == 19:
                raise
            pythoncom.PumpWaitingMessages()
            time.sleep(0.1)


def wrap(value):
    return DumbDispatch(value) if hasattr(value, "GetIDsOfNames") else value


def prop(obj, name):
    """Use authoritative DISPIDs, not pywin32's possibly stale method map."""
    def get():
        ole = getattr(obj, "_oleobj_", None)
        if ole is None:
            return getattr(obj, name)
        return wrap(ole.Invoke(ole.GetIDsOfNames(name), 0, pythoncom.DISPATCH_PROPERTYGET, True))
    return retry_read(get)


def method(obj, name):
    def bind():
        ole = getattr(obj, "_oleobj_", None)
        if ole is None:
            result = getattr(obj, name)
            if not callable(result):
                raise AttributeError(name)
            return result
        dispid = ole.GetIDsOfNames(name)
        return lambda *args: wrap(ole.Invoke(dispid, 0, pythoncom.DISPATCH_METHOD, True,
                                           *(getattr(arg, "_oleobj_", arg) for arg in args)))
    return retry_read(bind)


def put(obj, name, value):
    ole = getattr(obj, "_oleobj_", None)
    if ole is None:
        setattr(obj, name, value)
    else:
        dispid = retry_read(lambda: ole.GetIDsOfNames(name))
        ole.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYPUT, False, value)


def signature(layout):
    result = {name: plain(prop(layout, name)) for name in FIELDS}
    def output_pair(name, vt, initial):
        if getattr(layout, "_oleobj_", None) is None:
            return retry_read(lambda: method(layout, name)())
        def read():
            a, b = VARIANT(pythoncom.VT_BYREF | vt, initial), VARIANT(pythoncom.VT_BYREF | vt, initial)
            method(layout, name)(a, b)
            return a.value, b.value
        return retry_read(read)
    result["window"] = plain(output_pair("GetWindowToPlot", pythoncom.VT_VARIANT, None))
    result["custom_scale"] = plain(output_pair("GetCustomScale", pythoncom.VT_R8, 0.0))
    return result


def export_view(connection, file_path, timeout, wait_file, request_id=""):
    if not file_path:
        directory = os.path.join(tempfile.gettempdir(), "autocad_mcp_exports")
        os.makedirs(directory, exist_ok=True)
        file_path = os.path.join(directory, uuid4().hex + ".png")
    if os.path.exists(file_path):
        raise FileExistsError(f"Export target already exists: {file_path}")
    evidence = {"contract": "autocad-capture/1", "request_id": request_id,
                "file_path": file_path, "document": None, "layout": None,
                "stage": "preflight", "capture_mutations_started": False,
                "mutation_uncertain": False, "restoration_verified": False,
                "cleanup_verified": False, "before": None, "after": None,
                "backup_name": "_MCP_CAPTURE_" + uuid4().hex,
                "actions": [], "restoration_errors": [], "error": None}
    backup_created = copied = settings_touched = False
    backup = delete_backup = None
    before_names = None
    doc = layout = plot = configs = None
    layout_identity = None
    original = None

    def ready():
        app = getattr(connection, "app", None)
        if app is not None:
            for _attempt in range(40):
                state = retry_read(lambda: method(app, "GetAcadState")())
                if prop(state, "IsQuiescent"):
                    break
                pythoncom.PumpWaitingMessages()
                time.sleep(0.1)
            else:
                raise TimeoutError("CAD_CAPTURE_NOT_QUIESCENT")
        if evidence["document"] is not None:
            if prop(doc, "Name") != evidence["document"] or prop(prop(doc, "ActiveLayout"), "Name") != evidence["layout"]:
                raise RuntimeError("CAD_CAPTURE_BINDING_CHANGED")
            if app is not None and prop(prop(app, "ActiveDocument"), "Name") != evidence["document"]:
                raise RuntimeError("CAD_CAPTURE_ACTIVE_DOCUMENT_CHANGED")
            if layout_identity is not None:
                if (prop(prop(layout, "Document"), "Name") != evidence["document"]
                        or prop(prop(doc, "ActiveLayout"), "ObjectID") != layout_identity):
                    raise RuntimeError("CAD_CAPTURE_LAYOUT_OWNER_CHANGED")

    def names():
        return sorted(prop(retry_read(lambda: method(configs, "Item")(i)), "Name")
                      for i in range(prop(configs, "Count")))

    def mutate(name, action):
        ready()
        record = {"name": name, "acknowledged": False}
        evidence["capture_mutations_started"] = True
        evidence["actions"].append(record)
        try:
            result = action()
            record["acknowledged"] = True
            return result
        except Exception:
            evidence["mutation_uncertain"] = True
            raise

    try:
        doc = connection.document
        layout, plot, configs = prop(doc, "ActiveLayout"), prop(doc, "Plot"), prop(doc, "PlotConfigurations")
        evidence["document"], evidence["layout"] = prop(doc, "Name"), prop(layout, "Name")
        if getattr(layout, "_oleobj_", None) is not None:
            layout_identity = prop(layout, "ObjectID")
        ready()
        if not prop(layout, "ModelType"):
            raise ValueError("CAD_CAPTURE_MODEL_LAYOUT_REQUIRED")
        # Count and all extents/projection reads precede plot-setting mutation.
        count = prop(prop(doc, "ModelSpace"), "Count")
        method(doc, "Regen")(1)
        ready()
        window = None
        if count:
            get_variable = method(doc, "GetVariable")
            low, high = retry_read(lambda: get_variable("EXTMIN")), retry_read(lambda: get_variable("EXTMAX"))
            if any(not math.isfinite(v) for v in (*low, *high)) or any(a > b for a, b in zip(low, high)):
                raise ValueError("CAD_CAPTURE_EXTENTS_INVALID")
            translate = method(prop(doc, "Utility"), "TranslateCoordinates")
            corners = [retry_read(lambda x=x, y=y, z=z: translate(to_variant_point(x, y, z), 0, 2, False))
                       for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
            left, right = min(p[0] for p in corners), max(p[0] for p in corners)
            bottom, top = min(p[1] for p in corners), max(p[1] for p in corners)
            margin = max(max(right-left, top-bottom)*0.05, 1e-6)
            window = ([left-margin, bottom-margin], [right+margin, top+margin])
        before_names = names()
        get_variable = method(doc, "GetVariable")
        evidence["before"] = {"layout": signature(layout), "background": plain(retry_read(lambda: get_variable("BACKGROUNDPLOT"))),
                              "quiet": plain(prop(plot, "QuietErrorMode")), "configurations": before_names}
        # Resolve all native method metadata while the drawing is quiescent.
        add, restore_layout = method(configs, "Add"), method(layout, "CopyFrom")
        set_variable = method(doc, "SetVariable")
        refresh, plot_file = method(layout, "RefreshPlotDeviceInfo"), method(plot, "PlotToFile")
        set_window = method(layout, "SetWindowToPlot")
        evidence["stage"] = "backup"
        mutate("backup_add", lambda: add(evidence["backup_name"], True))
        backup_created = True
        backup = retry_read(lambda: method(configs, "Item")(evidence["backup_name"]))
        if prop(backup, "Name") != evidence["backup_name"]:
            raise RuntimeError("CAD_CAPTURE_BACKUP_IDENTITY_MISMATCH")
        copy_backup, delete_backup = method(backup, "CopyFrom"), method(backup, "Delete")
        mutate("backup_copy", lambda: copy_backup(layout))
        copied = True
        if signature(backup) != evidence["before"]["layout"]:
            raise RuntimeError("CAD_CAPTURE_BACKUP_MISMATCH")
        evidence["stage"] = "configure"
        settings_touched = True
        mutate("foreground", lambda: set_variable("BACKGROUNDPLOT", 0))
        mutate("quiet", lambda: put(plot, "QuietErrorMode", True))
        mutate("device", lambda: put(layout, "ConfigName", "PublishToWeb PNG.pc3"))
        mutate("refresh_device", refresh)
        mutate("rotation", lambda: put(layout, "PlotRotation", 0))
        if window:
            mutate("window", lambda: set_window(*(to_variant_double_array(p) for p in window)))
        mutate("plot_type", lambda: put(layout, "PlotType", 4 if window else 1))
        mutate("standard_scale", lambda: put(layout, "UseStandardScale", True))
        mutate("fit", lambda: put(layout, "StandardScale", 0))
        mutate("center", lambda: put(layout, "CenterPlot", True))
        method(doc, "Regen")(1)
        ready()
        evidence["stage"] = "plot"
        if not mutate("plot_to_file", lambda: plot_file(file_path)):
            raise RuntimeError("CAD_PLOT_REJECTED")
        evidence["stage"] = "artifact"
        wait_file(file_path, timeout)
    except Exception as error:
        original = error
        evidence["error"] = {"type": type(error).__name__, "message": str(error),
                             "hresult": getattr(error, "hresult", None), "traceback": traceback.format_exc()}
    finally:
        def recovery(name, action):
            try:
                mutate(name, action)
                return True
            except Exception as error:
                evidence["restoration_errors"].append({"action": name, "error": str(error)})
                return False
        layout_restored = not settings_touched
        if settings_touched and copied:
            # A native restore is issued once, after read-only readiness/binding.
            layout_restored = recovery("restore_layout", lambda: restore_layout(backup))
        if settings_touched:
            recovery("restore_background", lambda: set_variable("BACKGROUNDPLOT", evidence["before"]["background"]))
            recovery("restore_quiet", lambda: put(prop(doc, "Plot"), "QuietErrorMode", evidence["before"]["quiet"]))
        try:
            if evidence["before"] is not None:
                ready()
                evidence["after"] = {"layout": signature(prop(doc, "ActiveLayout")),
                                     "background": plain(retry_read(lambda: method(doc, "GetVariable")("BACKGROUNDPLOT"))),
                                     "quiet": plain(prop(prop(doc, "Plot"), "QuietErrorMode")), "configurations": names()}
                state_matches = all(evidence["after"][key] == evidence["before"][key]
                                    for key in ("layout", "background", "quiet"))
                # Keep the last recovery copy until actual layout/runtime
                # readback agrees; an acknowledged no-op is not restoration.
                if (backup_created and layout_restored and state_matches
                        and not evidence["mutation_uncertain"] and not evidence["restoration_errors"]):
                    try:
                        cleanup = delete_backup or method(backup, "Delete")
                    except Exception as error:
                        evidence["restoration_errors"].append({"action": "resolve_backup_delete", "error": str(error)})
                    else:
                        recovery("delete_backup", cleanup)
                    evidence["after"]["configurations"] = names()
                evidence["cleanup_verified"] = evidence["after"]["configurations"] == before_names
                evidence["restoration_verified"] = (evidence["before"] == evidence["after"] and
                                                     not evidence["mutation_uncertain"] and
                                                     not evidence["restoration_errors"])
        except Exception as error:
            evidence["restoration_errors"].append({"action": "verify_restore", "error": str(error)})
    if original or not evidence["restoration_verified"]:
        raise CADCaptureError(evidence) from original
    evidence["stage"] = "complete"
    return {"result": file_path, "capture": evidence} if request_id else file_path
