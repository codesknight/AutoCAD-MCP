# 后端能力、文档身份与执行回执

状态：P0 后续已完成房子与原始电路的联合回归（见 [PR #46](https://github.com/codesknight/AutoCAD-MCP/pull/46)）；[首批真实运行报告](../validation/2026-11-25-execution-evidence-p0.md)保留当时原生故障通过与复杂手稿未通过的历史。P1 第一批增加[普通 COM 文件交付契约](com-file-artifacts.md)。普通入口共 47 项工具，原 44 项工具的参数及成功内容保持兼容；`cader-cad/1` 专用入口仍使用自己的七项 DTO。

## 能力矩阵

`get_backend_status.capabilities.evidence_support` 使用 `autocad-backend-evidence/1`。以下不同保证不能互相替代：

| 能力 | 普通 COM | 普通 HTTP Bridge / 专用 profile |
| --- | --- | --- |
| instance_id | 当前 Python backend 生命周期 | 原生 Bridge 实例 |
| document_id | 同一 STA 内 canonical IUnknown 对应的文档生命周期 ID | Bridge 原生文档会话 ID |
| Python 重连 | 新身份、旧绑定失效 | 同一 Bridge 内可沿用原生身份 |
| 数据库 revision / 手工编辑跟踪 | unsupported / null，未伪造服务计数 | observed_database_events；事件序号包含回滚事件 |
| 请求对账 | 新显式入口的内存记录，当前 Python backend 内有效 | 原生 journal，同一 Bridge 内可跨 Python 重连 |
| 记录保留 | 最多 2048 项；终态十分钟，排队/执行中不按 TTL 淘汰 | 原生 journal 最多 2048 项，终态十分钟 |
| 原生动作 ACK | 显式回执列明逐项调用返回事实 | job/事务结果；不冒充逐个 ActiveX 调用 ACK |
| 原子批次 | 不支持；串行不是事务 | 原生批处理白名单；专用 profile 范围更小 |
| 独立只读重开 | 当前 Python backend 登记的 artifact、hash、独立只读文档；SaveAs 改工作图路径，见 P1 契约 | 本实例记录的 artifact_id、文件 hash、独立新文档 |
| 分页 / 字段投影 | 不支持版本绑定分页 | 支持；按工具 schema 的可选字段，revision 变化使游标失效 |
| since_revision / 像素到 CAD 变换 | 不支持 / unavailable | 不支持 / unavailable |

COM 的普通状态只返回工作线程信息及上次成功观测的绑定快照，文档项标记 `cached_not_live`，不会为状态查询启动 CAD 或读原生对象。需要当前原生观测时显式调用 `get_document_binding`；COM 仅附着现有实例，不隐式启动另一个 CAD。

COM 回执的 `service_request_fingerprint` 是本服务规范请求的内部冲突检查摘要，算法标为 `sha256-canonical-com-request-v1`。它与 Cader 对精确 `request_json` 的审计摘要、HTTP 原生 canonical hash 分开，三者都不构成重放授权。

## 文档身份

名称和文件路径仅作标签。COM 用 `QueryInterface(IID_IUnknown)` 的 canonical COM identity 区分文档，同名图不同 ID，SaveAs 保留当前文档 ID；关闭后的身份从文档集合中退役。切图、关闭、无法读取对象或输入 ID 不符时拒绝写入，不能因同名而重新绑定。重新创建 backend 会生成新 instance_id 和文档 ID；实体 ObjectID 只在对应文档内使用。

`get_document_binding` 返回 `instance_id/document_id/name/managed/read_only/revision/revision_mode`，HTTP 另保留已有文档字段。COM 的 `managed` 只表示当前连接成功创建并绑定的图纸，不是 Bridge 工作图的权限契约。新显式 COM 写入口只允许本连接创建的工作图，原有附着文档可以读取。旧工具保持既有权限行为，但同样使用更严格的文档身份检查。

## 显式 COM 执行

```json
{
  "instance_id": "<get_backend_status.instance_id>",
  "request_id": "client-persisted-001",
  "operation": "new_document",
  "arguments": {},
  "document_id": null
}
```

将上述参数交给 `execute_observed_operation`。其余操作必须携带新图回执的 `result_document_id`，使用内部 CAD 参数名，例如 `draw_line` 的 `start/end` 三维数组，而非旧 MCP `start_x/end_x`。准确白名单由能力声明返回：新建、线、圆、单行文字、移动、删除、保存、实体/全图查询及截图。

回包为 `{"receipt": {...}, "result": ...}`，回执失败时 MCP `isError=true`，仍保留完整结构化事实。旧工具不会自动改成这种 DTO；Cader 必须显式选择此入口才能使用新回执，不能把旧成功字符串当完整执行证据。

| stage | 可以推断的事实 |
| --- | --- |
| queued / preflight | 请求已登记；尚无写调用证据 |
| not_dispatched | 此执行入口未进入已跟踪的原生写调用 |
| dispatching | 至少一次原生写调用已进入，返回尚未确认 |
| native_acknowledged | 已记录的原生写动作均已返回；不等于后续观测或验收成功 |
| observing | 只读操作正在观测，没有新增原生写入 ACK |
| observation_failed | 已 ACK 后的观测/处理失败，或只读观测失败；不得改写成“没有执行” |
| result_unknown | 存在未 ACK 的原生写调用；不得自动重放 |
| completed | 本次执行和绑定观测均返回成功；不代表用户需求或文件独立验收通过 |

`native_actions` 保留动作名称及各自 acknowledged，包含辅助样式设置和已尝试的补偿清理。`native_acknowledged` 为这些动作全部返回的汇总；不宣称失败调用没有发生副作用。实体集合 `affected_entities` 按文档作用域返回已知的 created/modified/deleted ID；`complete=false` 时不得用空数组或部分集合宣称没有修改。回执不是数据库 revision、原子事务或任意图形的完整审计日志。

参数拒绝、身份不匹配和只读/非本连接工作图拒绝均在原生写前完成。原生变更调用不重试；只读方法解析可以有界等待。后续观测失败不会再次执行原操作，也不会用异常文字或实体数量推断未执行。

## 只读对账

调用 `get_execution_status(instance_id, request_id)`。COM 查询直接读 journal，不等待 STA，因此原生调用阻塞时仍可看见 pending/dispatching。相同 request_id、相同参数在保留窗口内只返回已有回执，不再次派发；不同参数报冲突且保留原记录。回执查询不是恢复写权限的授权。

HTTP 查询返回 `bridge-request/1` 和原生 operation/输入文档/expected_revision/source_artifact_id/job。新 Python 客户端先验证健康端点的实例身份，直接读原生 journal，不要求先在 CAD 主线程执行 `/status`，因此 CAD 忙时也能对账。客户端仍须核对原操作、请求、文档和结果身份。

记录缺失、过期、格式/身份不符或实例改变均返回 unresolved（或连接错误），不证明原写入未执行。COM Python 重启、Bridge/CAD 重启后不能从新实例找不到旧记录推断可安全重放。没有跨重启的持久执行日志，也不会自动解除 Cader 已有 unknown 屏障。

## 后续 P1 边界

截图仍沿用 `autocad-capture/1` 打印恢复回执；本轮没有校准像素映射。普通 COM save ACK 不证明文件 hash、独立重开或源图等价，文件操作不承诺跟实体事务一起回滚。字段投影/增量查询、截图几何映射及普通保存重开的对齐属于后续工作。
