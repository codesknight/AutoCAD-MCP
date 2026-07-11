"""标准电力单线图符号库目录。

符号本体是外部数据集（用户自己收集的电气图块，来源不明确能否自由再分发），
不随项目一起提交到仓库——这里只存一份"名称 -> 本机文件路径"的目录
（`symbol_library.json`），`insert_block` 工具本来就支持直接传 .dwg 文件路径，
所以这一层只是帮 AI 发现有哪些标准符号可用，不需要额外的插入逻辑。
在没有这份数据集的机器上（比如换了台电脑），`list_symbols()` 会老实返回空列表，
而不是报错。
"""
import json
import os

_LIBRARY_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "symbol_library.json")


def list_symbols() -> list[dict]:
    if not os.path.exists(_LIBRARY_PATH):
        return []
    with open(_LIBRARY_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    base_dir = data["base_dir"]
    if not os.path.isdir(base_dir):
        return []
    return [
        {"name_cn": s["name_cn"], "name_en": s["name_en"], "file": os.path.join(base_dir, s["file"])}
        for s in data["symbols"]
    ]
