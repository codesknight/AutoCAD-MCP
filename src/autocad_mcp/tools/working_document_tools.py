"""Explicit HTTP-only document lifecycle. Legacy tools retain their signatures."""
from typing import Annotated, Literal
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from autocad_mcp import state
from autocad_mcp.cad.models import WorkingDocumentJob, SavedArtifactJob

Identity = Annotated[str, Field(min_length=1,max_length=128)]
StableRequest = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")]
Revision = Annotated[int, Field(ge=0)]
Units = Literal["unitless","millimeters","centimeters","meters","inches","feet"]
Filename = Annotated[str, Field(min_length=5,max_length=200,pattern=r'^[^<>:"/\\|?*\x00-\x1f]+\.[dD][wW][gG]$')]

def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def create_working_drawing(instance_id: Identity, request_id: StableRequest,
                               units: Units = "millimeters",
                               output_directory: Annotated[str,Field(max_length=1024)] = "") -> WorkingDocumentJob:
        """在指定 HTTP 实例中新建受控工作图，返回 instance_id/document_id/revision/units/managed。
        先用 get_backend_status 取得实例；request_id 由客户端预先持久化，结果未知只查 job、不重放。
        output_directory 必须为已存在的本地绝对目录且不经过链接；空值创建独立私有输出目录。
        不修改旧工具的绑定；COM 不支持，不回退。示意图可明确选择 unitless。
        """
        return WorkingDocumentJob.model_validate(state.document_job("create_working_document",
            {"units":units,"output_directory":output_directory},instance_id=instance_id,request_id=request_id))

    @mcp.tool()
    def get_working_drawing(instance_id: Identity, document_id: Identity) -> WorkingDocumentJob:
        """只读取得指定 HTTP 文档的身份、当前 revision、单位及 Bridge 写权限，不依赖活动图纸。
        read_only 指 Bridge 权限；普通用户图纸只读。不会创建、关闭或重绑定文档。
        """
        return WorkingDocumentJob.model_validate(state.document_job("get_document_info",{},
            instance_id=instance_id,document_id=document_id))

    @mcp.tool()
    def save_working_drawing(instance_id: Identity, document_id: Identity, expected_revision: Revision,
                             request_id: StableRequest, file_name: Filename) -> SavedArtifactJob:
        """把受控工作图保存为其绑定目录中的新 DWG 文件，不覆盖任何已有文件，不重命名编辑器文档。
        返回 artifact_id、路径、SHA-256、字节数和保存时的源 revision。
        文件发布独立于图元事务，不承诺文件与图元整体回滚；失败可能 outcome_unknown，先对账。
        文件名不能含路径。保存成功不代表已重开或已通过几何验收。
        """
        return SavedArtifactJob.model_validate(state.document_job("save_document",{"file_name":file_name},
            instance_id=instance_id,document_id=document_id,expected_revision=expected_revision,request_id=request_id))

    @mcp.tool()
    def reopen_saved_drawing(instance_id: Identity, artifact_id: Identity,
                              request_id: StableRequest) -> WorkingDocumentJob:
        """校验本实例已登记保存件的哈希后，在 AutoCAD 中只读重开，返回新的文档身份。
        只接受 artifact_id，不接受任意文件路径；原工作图保持不变。返回文档 managed=false，禁止写入。
        用新的 document_id 调 query_entities_page 独立核验；不能按旧 object_id 跨文档寻址。
        重开成功只证明文件可打开；内容仍须客户端验证。实例重启后旧 artifact_id 不可恢复。
        """
        return WorkingDocumentJob.model_validate(state.document_job("reopen_artifact",{"artifact_id":artifact_id},
            instance_id=instance_id,request_id=request_id))
