import json

from mcp.server.fastmcp import FastMCP

from autocad_mcp.cad import reference_library
from autocad_mcp.state import get_controller


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def list_reference_drawings() -> str:
        """列出本机可用的真实电力工程参考图纸（完整图纸，不是单个符号），
        返回 [{"name_cn", "description", "file"}, ...]。file 是可以直接传给
        analyze_reference_drawing 的 .dwg 文件路径。这份数据集不在本机时返回
        空数组。用于"画出来的图不像真实图纸"时，先查一下真实图纸长什么样。
        """
        return json.dumps(reference_library.list_reference_drawings(), ensure_ascii=False)

    @mcp.tool()
    def analyze_reference_drawing(file_path: str, entity_type: str = "", max_entities: int = 500) -> str:
        """只读打开一份真实图纸（不影响、不修改当前正在编辑的文档），提取里面
        实体的真实空间布局（类型/坐标/包围盒），返回结构化 JSON，供画新图纸前
        参考真实的间距、朝向、连接线走法。file_path 用 list_reference_drawings
        返回的路径，或任何本机可访问的 .dwg 文件。可选按 entity_type
        （如 AcDbLine/AcDbCircle/AcDbBlockReference）过滤。
        """
        result = reference_library.analyze_reference_drawing(
            get_controller().connection, file_path, entity_type or None, max_entities,
        )
        return json.dumps(result, ensure_ascii=False)
