import json

from mcp.server.fastmcp import FastMCP

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
    def query_entities(entity_type: str = "") -> str:
        """查询当前图纸中的实体，可选按类型（如 AcDbLine/AcDbCircle）过滤，返回结构化 JSON。"""
        return json.dumps(get_query().query_entities(entity_type or None), ensure_ascii=False)

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
