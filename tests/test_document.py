"""save_drawing 的安全校验（见 CLAUDE.md「安全注意事项」+ devlog #13）。

用 C:\\Temp 而不是 pytest 的 tmp_path：这台机器上 tmp_path 落在 Windows 短文件名
路径（形如 LIUYAN~1）下时，AutoCAD 的 SaveAs 会报错——这是本机临时目录短路径命名
的固有怪癖，和 save_drawing 本身的代码无关（排查记录见 devlog 2026-07-11 续九），
换一个不带短名的固定目录规避掉。
"""
import os
import uuid

import pytest

from autocad_mcp.cad.controller import CADController

_SAFE_DIR = r"C:\Temp\pytest_autocad_mcp"


@pytest.fixture(autouse=True)
def _ensure_safe_dir():
    os.makedirs(_SAFE_DIR, exist_ok=True)


def test_save_drawing_rejects_bad_extension(scratch_doc):
    ctrl = CADController(scratch_doc)
    with pytest.raises(ValueError):
        ctrl.save_drawing(os.path.join(_SAFE_DIR, "test.txt"))


def test_save_drawing_rejects_missing_directory(scratch_doc):
    ctrl = CADController(scratch_doc)
    with pytest.raises(ValueError):
        ctrl.save_drawing(r"C:\this_dir_does_not_exist_pytest_xyz\test.dwg")


def test_save_drawing_overwrite_protection(scratch_doc):
    # 用带 uuid 的文件名，不用固定名字：AutoCAD 连接是跨 pytest 运行复用的长连接，
    # new_document() 只切到新文档、不会关掉旧文档，如果这里用固定路径，上一次跑
    # 测试时保存过的那个文档还开着占用同一个文件路径，这一次再 SaveAs 到同名路径
    # 会报 COM 错误（"保存文档时出错"）——这是测试之间的资源冲突，不是被测代码的 bug。
    ctrl = CADController(scratch_doc)
    path = os.path.join(_SAFE_DIR, f"pytest_overwrite_test_{uuid.uuid4().hex}.dwg")

    ctrl.save_drawing(path)
    with pytest.raises(ValueError):
        ctrl.save_drawing(path)  # same path again, overwrite=False by default -> rejected
    ctrl.save_drawing(path, overwrite=True)  # explicit opt-in -> succeeds
