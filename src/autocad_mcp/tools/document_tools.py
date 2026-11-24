import json
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

from autocad_mcp import state
from autocad_mcp.cad.capture import CADCaptureError
from autocad_mcp.cad.connection import CADNewDocumentError
from autocad_mcp.state import get_controller


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def new_drawing(request_id: str = "") -> CallToolResult:
        """新建一张空白图纸并切换过去（不会碰当前正在编辑的图纸），
        返回新图纸的名字。做实验性的绘图操作前建议先调用这个，
        避免不小心画到用户正在编辑的真实图纸上。
        """
        try:
            name = state.new_document()
            return CallToolResult(content=[TextContent(type="text", text=name)],
                                  structuredContent={"result": name})
        except CADNewDocumentError as exc:
            evidence = {**exc.evidence, "request_id": request_id or str(uuid4())}
            return CallToolResult(isError=True, structuredContent=evidence,
                                  content=[TextContent(type="text", text=json.dumps(evidence, ensure_ascii=False))])

    @mcp.tool()
    def save_drawing(file_path: str, overwrite: bool = False) -> str:
        """将当前图纸另存为指定路径。默认不允许 file_path 和当前文档的原始路径相同
        （避免覆盖用户正在编辑的真实图纸）；确实要覆盖原文件时传 overwrite=True。
        """
        get_controller().save_drawing(file_path, overwrite=overwrite)
        return f"saved to {file_path}"

    @mcp.tool()
    def export_current_view(file_path: str = "", request_id: str = "") -> CallToolResult:
        """把当前 AutoCAD 模型布局全图导出成 PNG；纸布局在修改前拒绝，不自动切换。
        不填 file_path 会生成临时路径。可选 request_id 关联打印状态恢复证据，
        不是重放授权。成功返回路径，关联调用附恢复回执；失败保留阶段及恢复证据。
        """
        try:
            controller = get_controller()
            value = (controller.export_current_view(file_path or None, request_id=request_id)
                     if request_id else controller.export_current_view(file_path or None))
            payload = value if isinstance(value, dict) else {"result": value}
            return CallToolResult(content=[TextContent(type="text", text=payload["result"])],
                                  structuredContent=payload)
        except CADCaptureError as exc:
            return CallToolResult(isError=True, structuredContent=exc.evidence,
                                  content=[TextContent(type="text", text=json.dumps(exc.evidence, ensure_ascii=False))])
