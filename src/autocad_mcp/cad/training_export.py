"""把真实图纸里的实体转换成"重建它需要调用哪个 MCP 工具、传什么参数"，用于批量
构建训练数据集（见 scripts/build_training_dataset.py）。

这是离线数据管道用的模块，不是 MCP 工具本身——不需要人工标注："真实实体的坐标"
本身就是最准确的标签，机械转换成对应工具调用的参数即可。

参数名严格对齐 tools/drawing_tools.py 里各工具的实际签名（拍平的 x/y/z，不是嵌套
列表），这样产出的训练样本可以直接当 MCP 工具调用参数回放验证，不需要额外转换层。
"""
import math

# 真实图纸数据集里混了不少和图纸内容无关的广告/水印文字（用户反馈过例子：
# "星欣设计图库"）——这些是图纸原作者/二次分发者留下的推广信息，不是电力工程
# 图纸本身的内容，训练数据里不该出现。用精确子串匹配而不是宽泛关键词（之前试过
# 用裸的 "QQ" 当关键词，会命中"1QQ"这种正常的设备/继电器位号，属于误伤，改成
# 只匹配具体、明确是广告的完整短语）。
_AD_NOISE_PHRASES = [
    "星欣设计图库",
]


def _is_ad_noise(text: str) -> bool:
    return any(phrase in text for phrase in _AD_NOISE_PHRASES)


def entity_to_tool_call(entity) -> dict | None:
    """把一个 COM 实体转换成 {"tool": 工具名, "args": {...}}。
    不认识的实体类型、或者提取属性失败，返回 None（调用方直接跳过，不是致命错误——
    真实图纸里总会有一些工具集覆盖不到的图元类型，比如样条曲线、标注、填充图案）。
    """
    try:
        object_name = entity.ObjectName
    except Exception:
        return None

    try:
        if object_name == "AcDbLine":
            start = entity.StartPoint
            end = entity.EndPoint
            return {
                "tool": "draw_line",
                "args": {
                    "start_x": start[0], "start_y": start[1], "start_z": start[2],
                    "end_x": end[0], "end_y": end[1], "end_z": end[2],
                    "layer": entity.Layer,
                },
            }
        if object_name == "AcDbCircle":
            center = entity.Center
            return {
                "tool": "draw_circle",
                "args": {
                    "center_x": center[0], "center_y": center[1], "center_z": center[2],
                    "radius": entity.Radius,
                    "layer": entity.Layer,
                },
            }
        if object_name == "AcDbArc":
            center = entity.Center
            return {
                "tool": "draw_arc",
                "args": {
                    "center_x": center[0], "center_y": center[1], "center_z": center[2],
                    "radius": entity.Radius,
                    "start_angle": math.degrees(entity.StartAngle),
                    "end_angle": math.degrees(entity.EndAngle),
                    "layer": entity.Layer,
                },
            }
        if object_name in ("AcDbPolyline", "AcDb2dPolyline"):
            points = _extract_polyline_points(entity, object_name)
            if not points:
                return None
            return {
                "tool": "draw_polyline",
                "args": {
                    "points": points,
                    "closed": bool(entity.Closed),
                    "layer": entity.Layer,
                },
            }
        if object_name == "AcDbBlockReference":
            insertion = entity.InsertionPoint
            return {
                "tool": "insert_block",
                "args": {
                    "block_name": entity.EffectiveName,
                    "position_x": insertion[0], "position_y": insertion[1], "position_z": insertion[2],
                    "scale": entity.XScaleFactor,
                    "rotation": math.degrees(entity.Rotation),
                    "layer": entity.Layer,
                },
            }
        if object_name == "AcDbText":
            text = entity.TextString
            if _is_ad_noise(text):
                return None
            position = entity.InsertionPoint
            return {
                "tool": "draw_text",
                "args": {
                    "position_x": position[0], "position_y": position[1], "position_z": position[2],
                    "text": text,
                    "height": entity.Height,
                    "layer": entity.Layer,
                    "rotation": math.degrees(entity.Rotation),
                },
            }
        if object_name == "AcDbMText":
            text = entity.TextString
            if _is_ad_noise(text):
                return None
            position = entity.InsertionPoint
            return {
                "tool": "draw_mtext",
                "args": {
                    "position_x": position[0], "position_y": position[1], "position_z": position[2],
                    "text": text,
                    "width": entity.Width,
                    "height": entity.Height,
                    "layer": entity.Layer,
                },
            }
    except Exception:
        return None
    return None


def _extract_polyline_points(entity, object_name: str) -> list[list[float]]:
    """`Coordinates` 是拍平数组，但两种多段线的步长不一样——实测确认过：
    `AcDbPolyline`（轻量级/现代 LWPOLYLINE）每个顶点 2 个数（x,y，z 另算，真实
    图纸里绝大多数是这种）；`AcDb2dPolyline`（老式重量级多段线，本项目自己的
    `draw_polyline` 工具画出来的就是这种）每个顶点是 3 个数（x,y,z）。一开始
    两种都按步长 2 解析，导致老式多段线读出来的坐标是错乱的（用自己的
    draw_polyline 画一个三角形测出来的），已修正为按类型区分步长。
    """
    try:
        coords = list(entity.Coordinates)
    except Exception:
        return []
    stride = 3 if object_name == "AcDb2dPolyline" else 2
    points = []
    i = 0
    while i + stride - 1 < len(coords):
        if stride == 3:
            points.append([coords[i], coords[i + 1], coords[i + 2]])
        else:
            points.append([coords[i], coords[i + 1], 0.0])
        i += stride
    return points
