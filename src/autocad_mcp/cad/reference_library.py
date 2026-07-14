"""真实电力工程图纸参考库——用户之前反馈"画出来的电力图不像"，根本原因是
AI 只能凭空猜坐标/间距/连接方式。这里提供一条新路子：不训练/微调大模型
（不符合本项目"不自己搞 NLP/训练层"的架构原则，见 CLAUDE.md），而是让 AI
在画图前先"查"一下真实图纸的实体布局，照着真实的间距/朝向/连接线样式来画。

真实图纸本体是外部数据集，不随项目提交（来源不明确能否自由再分发，做法和
symbol_library.py 一致）——这里只存一份"名称 -> 本机文件路径"的目录
（`reference_drawings.json`），`analyze_reference_drawing()` 负责实际读取。

实测过一个真实图纸例子（`35kV变电站改造主接线及总平面.dwg`）：全图 2912 个
实体，图块引用（AcDbBlockReference）只有 1 个——绝大多数"符号"是用直线/圆/
圆弧这些原始图元手工画出来的，不是插入的图块。这意味着"参考真实图纸"不能只看
图块引用，要把所有图元类型的真实空间分布都返回给 AI 参考。
"""
import json
import os
import time

from autocad_mcp.cad.query import _entity_summary

_CATALOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reference_drawings.json")


def list_reference_drawings() -> list[dict]:
    """列出本机可用的真实参考图纸目录。数据集不在本机时返回空数组，不报错。"""
    if not os.path.exists(_CATALOG_PATH):
        return []
    with open(_CATALOG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    base_dir = data["base_dir"]
    if not os.path.isdir(base_dir):
        return []
    return [
        {
            "name_cn": d["name_cn"],
            "description": d["description"],
            "file": os.path.join(base_dir, d["file"]),
        }
        for d in data["drawings"]
    ]


def _restore_active_document(app, original_active, retries: int = 10, delay: float = 0.3) -> None:
    # 切换活动文档紧跟在刚打开/关闭一个文档之后时，AutoCAD 偶尔会短暂拒绝 COM
    # 调用（RPC_E_CALL_REJECTED，"应用程序正忙"），重试几次就过去了——这个项目
    # 里已经不是第一次遇到这类 COM 忙碌瞬时错误。
    for _ in range(retries):
        try:
            app.ActiveDocument = original_active
            return
        except Exception:
            time.sleep(delay)


def open_reference_drawing(app, file_path: str, retries: int = 5, delay: float = 0.5):
    """只读打开一份参考图纸，绕开实测确认过的坑：`Documents.Open()` 的返回值和
    这个项目里 `Documents.Add()` 的返回值一样不可靠——动态派发（dynamic
    dispatch）偶尔还没解析完就被拿去用，报 `AttributeError('<unknown>.Close')`/
    `AttributeError('Open.ModelSpace')` 这种"方法名当属性名"的怪报错（在批量
    跑 scripts/build_training_dataset.py 时复现过好几次）。不信任 Open() 的
    直接返回值，改成 Open() 之后重新从 `app.ActiveDocument` 取一次（Open 本身
    会把新文档设为活动文档），并且主动触发一次真实属性访问确认解析完成，
    解析失败/COM 忙碌都在重试范围内。
    """
    last_exc = None
    for _ in range(retries):
        try:
            app.Documents.Open(file_path, True)  # ReadOnly=True；不信任返回值
            ref_doc = app.ActiveDocument
            _ = ref_doc.Name
            _ = ref_doc.ModelSpace
            return ref_doc
        except Exception as exc:
            last_exc = exc
            time.sleep(delay)
    raise last_exc


def close_reference_drawing(ref_doc, retries: int = 5, delay: float = 0.5) -> None:
    # Close() 本身也会偶发同一类"动态派发还没解析完"的 AttributeError
    # （批量跑训练数据脚本时复现过：AttributeError('<unknown>.Close')），
    # 跟 open_reference_drawing() 里的坑是同一个类型，一并规避。
    for _ in range(retries):
        try:
            ref_doc.Close(False)
            return
        except Exception:
            time.sleep(delay)


def analyze_reference_drawing(
    connection, file_path: str, entity_type: str | None = None, max_entities: int = 500,
) -> dict:
    """只读打开一份真实图纸（不影响、不修改当前正在编辑的文档），提取实体的真实
    空间布局（类型、坐标、包围盒），返回给 AI 参考真实图纸里符号的间距/朝向/
    连接方式，而不是凭空猜。全程不保存、不修改源文件（Documents.Open 的
    ReadOnly=True，Close 的时候也不保存）。
    """
    app = connection.app
    original_active = app.ActiveDocument
    ref_doc = open_reference_drawing(app, file_path)
    try:
        entities = []
        total = 0
        for entity in ref_doc.ModelSpace:
            total += 1
            try:
                object_name = entity.ObjectName
            except Exception:
                continue
            if entity_type and object_name != entity_type:
                continue
            if len(entities) >= max_entities:
                continue
            try:
                entities.append(_entity_summary(entity))
            except Exception:
                continue
        return {
            "file": file_path,
            "total_entity_count": total,
            "returned_count": len(entities),
            "entities": entities,
        }
    finally:
        close_reference_drawing(ref_doc)
        _restore_active_document(app, original_active)
        # 切走再切回活动文档，会让 connection 自己缓存的 document/model_space
        # COM 引用失效（同一类问题见 state.py 里那个已知的"连接不会自愈"缺口）。
        # 这次是本函数自己切换活动文档导致的，所以直接在这里用已有的
        # _wait_for_document 逻辑强制刷新，而不是留给调用方去踩坑。
        try:
            connection._wait_for_document(connection.config.connect_timeout)
        except Exception:
            pass
