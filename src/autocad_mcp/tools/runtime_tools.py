"""Additive runtime tools; explicit document identity for every new HTTP data operation."""
from typing import Annotated, Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator
from mcp.server.fastmcp import FastMCP
from autocad_mcp import state
from autocad_mcp.cad.models import BridgeJob

Point = Annotated[list[FiniteFloat], Field(min_length=3,max_length=3)]
StepId = Annotated[str,Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")]
DocumentId = Annotated[str,Field(min_length=1,max_length=128)]
RequestId = Annotated[str,Field(pattern=r"^$|^[A-Za-z0-9._-]{1,128}$")]
class Strict(BaseModel):
    model_config=ConfigDict(extra="forbid")

class LineArgs(Strict):
    start: Point
    end: Point
    layer: str | None = None
    @model_validator(mode="after")
    def nonzero(self):
        if self.start==self.end:
            raise ValueError("Line must have nonzero length")
        return self

class CircleArgs(Strict):
    center: Point
    radius: Annotated[FiniteFloat,Field(gt=0)]
    layer: str | None = None

class LayerArgs(Strict):
    name: Annotated[str,Field(min_length=1,max_length=255)]
    color: Annotated[int,Field(ge=1,le=255)] | None = None
    @model_validator(mode="after")
    def nonblank(self):
        if not self.name.strip():
            raise ValueError("Layer name must not be blank")
        return self

class LineStep(Strict):
    id: StepId
    operation: Literal["draw_line"]
    args: LineArgs

class CircleStep(Strict):
    id: StepId
    operation: Literal["draw_circle"]
    args: CircleArgs

class LayerStep(Strict):
    id: StepId
    operation: Literal["create_layer"]
    args: LayerArgs

Step=Annotated[LineStep|CircleStep|LayerStep,Field(discriminator="operation")]
Operations=Annotated[list[Step],Field(min_length=1,max_length=200)]
Fields=Literal["object_id","type","layer","handle","start_point","end_point","center","radius","bounding_box",
               "points","closed","text_string","insertion_point","height","rotation","width","measurement","dimension_line_point","text_style"]

class EntityPage(Strict):
    document_id: str
    revision: Annotated[int,Field(ge=0)]
    items: Annotated[list[dict],Field(max_length=1000)]
    count: Annotated[int,Field(ge=0,le=1000)]
    has_more: bool
    next_cursor: str | None
    unsupported_geometry_types: list[str] = Field(default_factory=list)
    @model_validator(mode="after")
    def consistent(self):
        if self.count!=len(self.items) or self.has_more!=bool(self.next_cursor):
            raise ValueError("Inconsistent Bridge page envelope")
        return self

class BackendStatus(BaseModel):
    model_config=ConfigDict(extra="allow")
    backend: Literal["com","http"]
    state: str
    capabilities: dict
    documents: list[dict]
    connection_state: str | None = None
    queue_depth: int | None = None
    instance_id: str | None = None
    active_document_id: str | None = None
    bound_document_id: str | None = None
    cad_version: str | None = None
    revision_mode: str | None = None

def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def get_backend_status() -> BackendStatus:
        """查询后端生命周期、能力及 HTTP 文档会话。COM 状态查询不隐式启动 CAD；
        HTTP 返回实例、活动/旧工具绑定文档及 revision。写入前从此处获取 document_id。
        """
        return BackendStatus.model_validate(state.runtime_status())

    @mcp.tool()
    def get_job_status(request_id: Annotated[str,Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")]) -> BridgeJob:
        """查询 HTTP Bridge 请求状态。写入结果未知时只查询该 request_id，不自动重放；
        journal 仅在当前实例的有界保留窗口内有效，JOB_NOT_FOUND 不证明写入从未执行。
        """
        return state.job_status(request_id)

    @mcp.tool()
    def execute_atomic_batch(
        document_id: DocumentId, operations: Operations,
        request_id: RequestId = "", expected_revision: Annotated[int,Field(ge=0)] | None = None,
    ) -> BridgeJob:
        """在显式指定的 HTTP Bridge 自建文档中执行 1–200 项原子操作。
        仅支持 create_layer/draw_line/draw_circle，坐标使用三元素 WCS 数组；
        step id 必须唯一，不支持跨步骤动态引用。失败整体回滚，不支持文件操作。
        返回 request_id、document_id、revision 和逐步结果。COM 明确不支持，无回退。
        相同 request_id 只在原实例有效窗口内去重；结果未知时用 get_job_status 查询。
        """
        ids=[step.id for step in operations]
        if len(set(ids))!=len(ids):
            raise ValueError("Batch step IDs must be unique")
        return state.atomic_batch(document_id,[s.model_dump(exclude_none=True) for s in operations],
                                  request_id or uuid4().hex,expected_revision)

    @mcp.tool()
    def query_entities_page(
        document_id: DocumentId,
        entity_type: Annotated[str,Field(max_length=128)] = "",
        layer: Annotated[str,Field(max_length=255)] = "",
        fields: Annotated[list[Fields],Field(max_length=19)] | None = None,
        limit: Annotated[int,Field(ge=1,le=1000)] = 200,
        cursor: Annotated[str,Field(max_length=2048)] = "",
    ) -> EntityPage:
        """分页查询显式 HTTP 文档，支持类型、图层和字段裁剪。身份字段始终包含。
        每页最多 1000 项；继续查询须保留相同 document_id/过滤/fields/limit 并传 next_cursor。
        游标绑定实例、文档和观察到的 revision，图纸变化或游标过期后需从第一页重读。
        旧 query_entities 签名及 1000 项限制保持不变；COM 暂不支持此分页接口。
        """
        if fields is not None and len(fields)!=len(set(fields)):
            raise ValueError("Query fields must be unique")
        page=EntityPage.model_validate(state.query_page(document_id,entity_type,layer,fields,limit,cursor))
        if page.document_id!=document_id or page.count>limit:
            raise ValueError("Bridge page does not match requested document or limit")
        return page
