"""Coordinate/COM VARIANT conversion helpers."""
import pythoncom
import win32com.client

Point = tuple[float, float, float]


def to_variant_point(x: float, y: float, z: float = 0.0) -> win32com.client.VARIANT:
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [x, y, z])


def to_variant_double_array(values: list[float]) -> win32com.client.VARIANT:
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, values)


def to_variant_object_array(objects: list) -> win32com.client.VARIANT:
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, objects)
