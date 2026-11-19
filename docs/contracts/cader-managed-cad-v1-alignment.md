# Cader / MCP 公共契约：MCP 侧对齐意见

日期：2026-11-19。状态：**审阅与对齐提案，尚未由双方冻结，尚未实现 cader-cad/1 适配端点**。

审阅输入为 Cader `be2887f` 的 `docs/contracts/managed-cad-v1.md`、机读 schema 与消费代码；MCP 基线为 `5fbd007`。Cader 文档用于描述其需求，不作为 MCP 已实现或双方已同意的能力声明。本轮不修改 Cader，不改变 COM 默认配置，不执行 CAD 写入或 DWG 联合验收。

## 当前结论与机器证据

仓库默认配置的真实 stdio MCP 返回 `backend=com`，注册 44 个工具。Cader 的协议名 `cader-cad/1` 目前没有在 MCP 端实现。单独选择 HTTP 后端只解决后端选择问题，仍有接口及语义差异。

只读对照脚本确认：Cader 请求的 `create_working_document`、`save_document_as`、`reopen_document` 三个 MCP 工具名不存在。其余同名工具也不能据此推定结构兼容。此前 HTTP 实测的六类返回与 Cader 当前 schema 均不直接兼容。

证据见 [结构对照结果](evidence/cader-v1-alignment-2026-11-19.json)。其中当前后端与工具目录来自本轮只读 stdio 调用；HTTP 返回来自明确标注的既有合成实机记录，是历史结构样本，不是本轮连接 HTTP 或 DWG 闭环通过。

## MCP 接受的公共目标

- 显式选择 HTTP；复用已有 Bridge，不因能力缺失回退 COM 或当前图纸。
- 客户端先持久化 request_id，再提交写请求；超时、断链、实例变化和 journal 丢失不自动重放。
- 以 instance_id/document_id/revision 绑定工作图；文件名不充当文档身份。
- 文件发布独立于图元事务，禁止覆盖，记录真实文件哈希，使用独立重开文档验收。
- 第一轮只验证固定 fixture 的 line/circle/text；图片计划与广泛 CAD 对象能力另行验收。
- Agent、技能和模型输出不授予写权限。Cader 保持程序专用调用及其自身授权/计划审查。

## 可由 MCP 适配的接口差异

以下是拟实施的映射，不是现有别名或已开放能力：

| Cader 草案 | 当前 MCP / Bridge | 拟由 MCP 负责的适配 |
| --- | --- | --- |
| create_working_document | MCP create_working_drawing；内部 Bridge 恰有同名 operation | 在显式版本化 MCP profile 中提供 Cader 名称；内部 operation 不是可直接发现的 MCP 工具 |
| save_document_as | save_working_drawing，接受 file_name 与已绑定目录 | 校验 output_path 位于预先授权目录并禁止覆盖后映射保存；不接受任意目标路径 |
| reopen_document | reopen_saved_drawing，返回只读新文档 | 增加 profile 名称映射；保留独立身份和实际写权限 |
| contract_version + document/artifact | BridgeJob，元数据在 result；instance 在外层 | 生成版本化 DTO，逐项核对实例、请求、文档、revision，再返回；不改旧 44 项返回 |
| capabilities.managed_documents/atomic_operations/save_as/reopen/job_status/query_entities | controlled_documents/batch_operations/file_operations/query_pagination 等 | 根据真实协商能力发布 profile 能力；三操作交集之外不宣称可验收 |
| units 字符串 | units={code,name}；输入为完整英文名 | unitless→0，mm→4，cm→5，m→6，in→1，ft→2；转为现有 unitless/millimeters/centimeters/meters/inches/feet。layout 由 Cader 显式转换为 unitless |
| draw_text.args.point | draw_text.args.position | 无损字段映射，第一轮仅接受无旋转的规范文字 |
| results[{id,status,object_id}]，ID 为字符串 | result[{id,result}]，entity alias 为整数 | 校验每步 ID/alias 唯一后生成字符串 alias；alias 始终与 document_id 共同使用，不跨文档比较 |
| query 的 instance_id、expected_revision、nullable cursor | 现有 MCP 未声明前两个参数，初始 cursor 为字符串空值 | 新 profile 必须真正传递并执行实例/revision 校验；null→空游标。不得仅让额外参数被忽略 |
| query.items={object_id,operation,args} | CAD 类型及几何/文字/样式字段 | 仅为已验证的三操作规范子集生成 DTO；旋转、法向、拟合、非规范线型等不可表达属性须拒绝或显式报 unsupported |
| artifact.path/byte_size/document_id/revision | file_path/bytes/source_document_id/saved_revision | 保留原保存来源语义映射，携带真实 instance_id；不拿保存之后的当前 revision 冒充保存时 revision |
| failed/outcome 与普通 JSON job | 原失败会抛工具错误；journal 使用 rolled_back 等状态 | 新 profile 规范化终态与 error outcome，保留未知结果。旧工具错误行为不变 |

ID 字符集也需对齐：Cader 允许冒号，MCP 的部分 request/step ID 校验目前不允许。当前固定 fixture 的 UUID 与步骤名处于交集，不代表整个声明范围已兼容。适配前必须固定字符集与请求哈希规则。

## 必须先冻结的语义

### 1. 重开文档的 managed 与写权限

MCP 当前 managed 表示 Bridge 允许写入的自建文档。重开保存件是独立的只读文档，返回 managed=false/read_only=true；原工作图保留可写。Cader 当前 CreateResult 和 ReopenResult 共用严格 Binding，要求 managed=true，运行时也对两者使用同一个 checkBinding。这会拒绝当前正确的只读重开结果。

MCP 建议：区分 WorkingBinding 与 VerificationBinding。工作图为 managed=true/read_only=false；验收图为 managed=false/read_only=true，带 source_artifact_id。Cader 对重开阶段使用单独校验，并禁止任何写工具使用验收图身份。

如双方希望 managed 只表示“来源由服务管理”，应另立明确的 ownership/write_allowed 字段及新版本语义；不能沿用当前字段同时表达互相矛盾的写权限。本提案优先保留现有 MCP 权限含义。

### 2. 回滚、未执行与 revision

MCP 的 revision_mode=observed_database_events。ObjectAppended/ObjectModified/ObjectErased 事件会使 revision 前进，包括回滚过程。已验证“实体/图层/样式无残留”不意味着事件序号不变；当前原生失败 job 也未保证包含失败后的 revision。

Cader 当前要求 failed + rolled_back/not_executed 时 revision 等于旧绑定。尤其当请求因 stale revision 被拒绝时，当前文档 revision 本就可能与预期不同。因此 MCP 不承诺失败后回到旧序号，也不会重置事件计数以满足该断言。

建议公共规则：outcome 描述本请求副作用，revision 描述实际观察状态，两者分别判定。MCP 适配时补充权威的失败后 revision（能确定时）；Cader 确认失败后终止本轮写入，用返回/重读的 revision 独立核验回滚状态。权威状态缺失或身份不符时保持冻结。known rolled_back 与 unknown 仍需区分，均不自动续写或重放。

若改用“仅已提交事务计数”的逻辑版本，必须新增 revision_mode 与单独实现，并处理外部编辑，不能把现有观察序号静默改义。

### 3. 输出目录授权发生在何时

Cader 在 create 中没有传输出目录，到 save 时才给绝对 output_path；MCP 在创建时绑定输出目录，save 只接受文件名。当前 Cader 固定使用其工作区的 `.cader/artifacts`，测试 fixture 使用现成图层 0，不需要隐式创建图层。

MCP 建议在专用 HTTP profile 的私有服务配置中显式授权 Cader 的 artifacts 目录，再绑定每张工作图；save 必须验证完整 output_path 确实落入该目录，不覆盖文件、不穿越链接。另一可选方案是在 create 请求中加入 output_directory，由 Cader 维护方实现。先确定方案，再开放保存接口。

### 4. 对账按操作区分输入与输出文档身份

批处理/保存的结果应匹配原工作图；创建/重开会产生新文档，重开应匹配 artifact 并返回新的验收文档 ID。Cader 当前对账分支在 binding 存在时统一要求 job.document_id 等于原 binding.document_id，对重开 job 可能过严。

双方应约定 job 的 request_document_id / result_document_id 或等价的逐操作校验规则，避免把合法重开结果记为身份错配。仍保留“只查询、不自动继续写入”的冻结原则。

## 后端配置与协议适配是两项工作

[HTTP 配置示例](../../examples/cader/http-backend.example.json) 是可由现有 MCP Config 解析的独立配置，不含凭据，不修改默认 COM，也不宣称已经支持 cader-cad/1。

Cader 现有 env_refs 可将 CADER_AUTOCAD_HTTP_CONFIG 映射为子进程 AUTOCAD_MCP_CONFIG；其值须为独立 JSON 的绝对路径。AUTOCAD_BRIDGE_TOKEN 继续从私有环境传入，与已启动 Bridge 的令牌一致。MCP 传输仍可为 stdio，HTTP 指的是 Python→AutoCAD Bridge 后端。单独在 Cader 指定 --backend http 不会替它切换 MCP 子进程配置。

建议实现显式的版本化 MCP profile/入口，消费并验证 cader-cad/1 DTO，内部调用现有 HTTP backend/native Bridge。普通 autocad_mcp.server 及其 44 项工具保持兼容；不创建第二套 AutoCAD 插件或事务/请求 journal。该 profile 当前尚不存在。

## 双方责任与验收门槛

MCP 方负责：上述名称/字段/单位/错误 DTO 适配、真实实例与 revision guard、输出目录授权、受限查询规范化、schema 与 fixture 导出。Cader 方负责：其维护者确认并调整只读重开 Binding、失败 revision 规则及按操作对账，继续维护授权、写锁和业务终态。双方共同冻结版本、schema 哈希与例子。

对齐完成后按顺序验收：

1. 真实 stdio 发现所约定七项工具，HTTP 状态通过双方同一份 schema，能力交集明确。
2. 无 CAD 的共享正反例覆盖字段/单位、只读重开、revision、未知结果及 unsupported 属性，不把结构通过当 DWG 通过。
3. 用户授权的独立 CAD 测试实例中，由 **Cader 原生 CLI** 执行现有三图元 fixture：新图→批处理→独立查询→保存文件哈希→只读重开→独立查询。
4. 验证覆盖拒绝、错误实例、stale revision、明确回滚、结果未知冻结等负例。记录真实业务状态、DLL/schema/客户端版本、每次请求和清理结果。
5. 完成后才能声明 Cader↔MCP 的真实 DWG 闭环验收。此前 MCP 的 42 次独立实测、Cader 的 fake 测试和本轮 schema 对照分别保留自己的范围。

复核命令（退出码 2 表示不兼容诊断，不会绘图）：

```powershell
python scripts/check_cader_contract.py --schema '<Cader仓库>/configs/contracts/cader-v1.schemas.json' --output '<新的对照报告.json>'
```
