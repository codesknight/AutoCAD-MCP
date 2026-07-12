import json

from mcp.server.fastmcp import FastMCP

from autocad_mcp.cad import symbol_library
from autocad_mcp.state import get_controller, get_query


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def list_layers() -> str:
        """列出当前图纸的所有图层名（JSON 数组）。"""
        return json.dumps(get_query().list_layers(), ensure_ascii=False)

    @mcp.tool()
    def list_blocks() -> str:
        """列出当前图纸里已有的、可插入的图块定义名（JSON 数组）。"""
        return json.dumps(get_controller().list_blocks(), ensure_ascii=False)

    @mcp.tool()
    def list_symbol_library() -> str:
        """列出本机可用的标准电力单线图符号库（断路器/隔离开关/变压器/避雷器等），
        返回 [{"name_cn", "name_en", "file"}, ...]。file 是可以直接传给 insert_block
        的 .dwg 文件路径。这份库不在本机时返回空数组。
        """
        return json.dumps(symbol_library.list_symbols(), ensure_ascii=False)

    @mcp.tool()
    def query_entities(entity_type: str = "") -> str:
        """查询当前图纸中的实体，可选按类型（如 AcDbLine/AcDbCircle）过滤，返回结构化 JSON。"""
        return json.dumps(get_query().query_entities(entity_type or None), ensure_ascii=False)

    @mcp.tool()
    def query_entities_in_region(
        corner1_x: float, corner1_y: float, corner1_z: float,
        corner2_x: float, corner2_y: float, corner2_z: float,
        mode: str = "crossing",
        entity_type: str = "",
    ) -> str:
        """查询矩形区域 (corner1, corner2) 内的实体，比 query_entities 全表扫描快，
        适合复杂图纸只关心某一块区域的场景。mode="crossing"（默认，区域内或和边界
        相交都算）或 "window"（只有完全被区域包住才算，偶发不稳定，见函数内部注释）。
        可选按 entity_type（如 AcDbLine/AcDbBlockReference）过滤。返回结构化 JSON。
        """
        results = get_query().query_entities_in_region(
            (corner1_x, corner1_y, corner1_z),
            (corner2_x, corner2_y, corner2_z),
            mode=mode,
            entity_type=entity_type or None,
        )
        return json.dumps(results, ensure_ascii=False)

    @mcp.tool()
    def get_entity(object_id: int) -> str:
        """按 ObjectID 获取单个实体详情。"""
        return json.dumps(get_query().get_entity(object_id), ensure_ascii=False)

    @mcp.tool()
    def delete_entity(object_id: int) -> str:
        """按 ObjectID 删除实体。"""
        get_query().delete_entity(object_id)
        return f"deleted object_id={object_id}"

    @mcp.tool()
    def move_entity(object_id: int, offset_x: float, offset_y: float, offset_z: float) -> str:
        """把实体沿 (offset_x, offset_y, offset_z) 平移（相对位移，不是绝对坐标）。"""
        get_query().move_entity(object_id, (offset_x, offset_y, offset_z))
        return f"moved object_id={object_id}"

    @mcp.tool()
    def rotate_entity(
        object_id: int, base_x: float, base_y: float, base_z: float, angle: float,
    ) -> str:
        """绕 (base_x, base_y, base_z) 旋转实体，angle 单位为度。"""
        get_query().rotate_entity(object_id, (base_x, base_y, base_z), angle)
        return f"rotated object_id={object_id}"

    @mcp.tool()
    def copy_entity(object_id: int, offset_x: float, offset_y: float, offset_z: float) -> str:
        """复制一份实体并沿偏移量平移，原实体不变，返回新实体的 ObjectID。"""
        new_id = get_query().copy_entity(object_id, (offset_x, offset_y, offset_z))
        return f"copy_entity ok, object_id={new_id}"

    @mcp.tool()
    def scale_entity(
        object_id: int, base_x: float, base_y: float, base_z: float, scale_factor: float,
    ) -> str:
        """以 (base_x, base_y, base_z) 为基点等比缩放实体。"""
        get_query().scale_entity(object_id, (base_x, base_y, base_z), scale_factor)
        return f"scaled object_id={object_id}"

    @mcp.tool()
    def mirror_entity(
        object_id: int,
        point1_x: float, point1_y: float, point1_z: float,
        point2_x: float, point2_y: float, point2_z: float,
        erase_source: bool = False,
    ) -> str:
        """以 point1-point2 连线为镜像轴，返回镜像后新实体的 ObjectID。
        erase_source=True 时删除原实体（相当于翻转而不是镜像出一份新的）。
        """
        new_id = get_query().mirror_entity(
            object_id, (point1_x, point1_y, point1_z), (point2_x, point2_y, point2_z), erase_source
        )
        return f"mirror_entity ok, object_id={new_id}"

    @mcp.tool()
    def get_block_attributes(object_id: int) -> str:
        """取图块引用的属性（tag -> value），返回 JSON。"""
        return json.dumps(get_query().get_block_attributes(object_id), ensure_ascii=False)

    @mcp.tool()
    def set_block_attribute(object_id: int, tag: str, value: str) -> str:
        """修改图块引用某个属性标签的值。"""
        get_query().set_block_attribute(object_id, tag, value)
        return f"set_block_attribute ok, object_id={object_id}, tag={tag}"

    @mcp.tool()
    def bulk_get_block_attributes(object_ids: list[int] | None = None, block_name: str = "") -> str:
        """批量取多个图块引用的属性。传 object_ids 就只查这些；不传就按 block_name
        过滤（block_name 也不传就是图纸里所有带属性的图块引用）。返回 JSON：
        {"object_id": {"tag": "value", ...}, ...}。
        """
        results = get_query().bulk_get_block_attributes(object_ids or None, block_name or None)
        return json.dumps({str(k): v for k, v in results.items()}, ensure_ascii=False)

    @mcp.tool()
    def bulk_set_block_attributes(updates: list[dict]) -> str:
        """批量设置图块属性。updates 是 [{"object_id":.., "tag":.., "value":..}, ...]，
        单条失败不影响其它条。返回每条的执行结果 JSON。
        """
        return json.dumps(get_query().bulk_set_block_attributes(updates), ensure_ascii=False)

    @mcp.tool()
    def validate_block_attributes(required_tags: list[str], block_name: str = "") -> str:
        """校核图块属性完整性：检查图纸里的图块引用（不传 block_name 就是全部）是否
        都有 required_tags 里列出的每个属性标签，且值不为空。只返回有问题的条目
        （缺失/空值），JSON 数组，没问题就返回空数组。
        """
        results = get_query().validate_block_attributes(required_tags, block_name or None)
        return json.dumps(results, ensure_ascii=False)
