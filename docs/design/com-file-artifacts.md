# 普通 COM 文件交付契约（P1 第一批）

本契约扩展普通入口的 `execute_observed_operation`，不新增工具名称、不改变旧 `save_drawing`，COM 仍为默认后端。HTTP/`cader-cad/1` 的文件接口继续使用各自既有 DTO。能力发现以 `get_backend_status.capabilities.evidence_support` 为准。

## 调用顺序

每个请求都使用客户端持久化的唯一 `request_id` 和当前 `instance_id`。先经显式 `new_document` 创建工作图，从 `get_document_binding` 获取工作 `document_id`。以下是三个操作的参数，外层仍为普通显式回执工具的参数：

```json
{
  "instance_id": "<current-instance>",
  "document_id": "<working-document>",
  "request_id": "deliver-001",
  "operation": "save_document_artifact",
  "arguments": {
    "output_directory": "D:\\CAD-Deliveries",
    "file_name": "house.dwg"
  }
}
```

`output_directory` 必须是已存在的本地绝对目录，拒绝 UNC、父目录跳转、符号链接及 reparse point。目录首次绑定到该工作图后不能更换；服务创建独占的 `artifact-<id>` 子目录，因此相同文件名的后续请求也不会覆盖之前的交付。客户端必须使用返回的实际 `path`。

保存返回 `autocad-file-artifact/1`：`artifact_id / instance_id / source_document_id / path / output_directory / sha256 / byte_size / state / saved_at`，并明确 `save_semantics=save_as_renames_source`。原生 COM SaveAs 会改变当前工作图名称和路径，文档生命周期 ID 不变；它不宣称 HTTP 的复制保存语义。保存后检查实际 FullName、DWG 文件头及完整 SHA-256，`state=saved` 只表示文件保存与读取检查完成，`verification=not_performed`。

接着保持外层 `document_id=<working-document>`，使用：

```json
{"operation":"reopen_document_artifact","arguments":{"artifact_id":"<saved-artifact>"}}
```

只接受本 backend 登记且 SHA/大小仍一致的 artifact。服务创建字节一致、文件名唯一的副本，原生 `Documents.Open(path, true)` 仅调用一次；必须观察到恰好一个新文档且原集合保留，实际 ReadOnly/FullName 正确。返回 `autocad-verification-document/1`：独立 `document_id`、`source_document_id / source_artifact_id / path / sha256 / byte_size`，以及 `managed=false / read_only=true`。恢复原工作图活动状态，保持旧工具的工作绑定。

若存在其他未命名且无模型实体的文档，重开在原生 Open 前以 `OTHER_EMPTY_DOCUMENT_OPEN` 拒绝。AutoCAD 可能自动替换这类文档；客户端应先让用户显式处理它，服务不代为关闭其他文档。观察失败不重复 Open。

最后，外层和内层均指定新的验收 `document_id`：

```json
{"operation":"query_verification_entities","arguments":{"document_id":"<verification-document>"}}
```

查询直接读取登记的验收文档，不切换工作绑定；校验文档仍存在、只读、Saved、路径及文件摘要，读取后再次检查原生状态。返回 `autocad-verification-query/1`，`items` 为现有 COM 实体摘要，`geometry_scope=legacy_summary_partial / snapshot_revision=null`。这批查询不承诺完整实体序列化、分页、字段投影或原子快照；完整语义验收仍需独立 verifier。只读文件允许 AutoCAD 内存编辑，因此检测到未保存修改时拒绝验收。

## 回执、失败与生命周期

- 三项操作出现在 `evidence_support.execution_receipts.operations`。成功结果同时登记在回执 `file_result`，可通过 `get_execution_status` 取回；同一 request_id 重复查询不会重新 SaveAs/Open。冲突请求仍拒绝。
- `file_progress` 区分 prepared、原生 ACK 后尚未验证、saved/readonly_opened；ACK 后路径、文件头、集合、激活等检查失败，属于 observation_failed。无 ACK 仍是 result_unknown，禁止自动重放未知写入。
- 文件动作独立于实体事务。保存失败可能留下文件，重开失败可能留下只读文档；不自动删除、不承诺原子回滚，也不把文件失败解释为原图实体未执行。
- artifact/验收绑定仅在当前 Python backend 内有效，各最多 2048 项；不是跨进程持久化账本。请求回执沿用 P0 十分钟终态窗口。重启、记录缺失或旧 instance 失效后，不能按文件名恢复授权或推断安全重放。
- COM 继续返回 `revision=null / revision_mode=unsupported`，没有权威手工编辑版本。验收文档不成为工作图，显式写入口不能以其 ID 写入。

本批实机范围、原始失败与后续 P1 工作见[验收报告](../validation/2026-11-25-com-artifact-p1.md)。Cader 尚需接入这些新操作并重新提交客户端联合闭环证据。
