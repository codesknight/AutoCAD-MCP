# Cader 受控 CAD 接口：cader-cad/1

状态：MCP 已实现修订 2，固定几何计划的真实 Cader CLI / DWG 闭环已通过。[验收报告](../validation/2026-11-19-cader-managed-profile.md)。共享 manifest 仍保留 Cader 原始 `unfrozen` 状态，本文不代替双方发布冻结。

## 选择入口

普通 `python -m autocad_mcp.server` 保持 **44 个工具、COM 默认**。程序客户端显式使用独立的 stdio 入口：

```powershell
$env:AUTOCAD_MCP_CONFIG = 'D:\config\autocad-http.json'
# AUTOCAD_BRIDGE_TOKEN 由本机私有环境注入，不写入仓库或命令日志。
python -m autocad_mcp.managed_server
```

配置采用 [HTTP 配置示例](../../examples/cader/http-backend.example.json)，预先安装并启动新版 [Bridge](http-bridge.md)。独立 profile 只接受 HTTP；配置仍为 COM、Bridge 过旧或缺少原生 request records 时明确失败，不自动回退。`tools/list` 不启动 CAD，关闭 stdio 会话只释放客户端连接。

[Cader MCP 配置示例](../../examples/cader/managed-profile.example.json) 使用现有 Cader `env_refs`，将宿主机的配置路径、私有 token 和源码路径传给子进程。安装 wheel 后可省略源码 `PYTHONPATH` 映射。示例文件须替换绝对路径；不会修改 Cader 的代码、策略或默认 MCP 配置。

## 公共接口与转换

固定 schema SHA-256：`e239266ee97ccd64284f6a6b5896eb57532b0f18eb5769dad3899e614191dd28`。运行时携带同一份原始 schema，校验所有公共请求和结果；`structuredContent` 直接返回 DTO，并提供等价 JSON 文本，不增加 `result` 包装。

| 工具 | 行为 / 原生映射 |
| --- | --- |
| `get_backend_status` | 实例身份、`observed_database_events`、工作图绑定和此 profile 实际能力 |
| `create_working_document` | 显式单位及输出目录；返回 `managed=true/read_only=false` 工作图 |
| `execute_atomic_batch` | 原生 `_batch`；最多 100 步，原序映射 ID；失败整体回滚 |
| `get_job_status` | 按 request_id 读取原生记录；不提交、重试或补造身份 |
| `query_entities_page` | 明确实例、文档、预期 revision；游标与相同查询版本绑定 |
| `save_document_as` | 原生 `save_document`；完整输出路径映射为绑定目录内文件名，禁止覆盖 |
| `reopen_document` | 原生 `reopen_artifact`；哈希验证后返回不同 document_id、`managed=false/read_only=true` 的验收图 |

第一轮受控写入仅接受 **图层 0 的直线、圆和单行文字**。文字 `point` 映射为原生 `position`，显式 `rotation=0`；alias 转为字符串，只在所属文档内有效。ID 使用 `^[A-Za-z0-9._-]{1,128}$`。单位映射为 unitless/mm/cm/m/in/ft，原生代码为 0/4/5/6/1/2；适配器不猜测 Cader 的计划单位。

这七个工具与普通入口的同名工具具有独立的版本化 DTO。不得把普通入口的返回值直接作为本契约回包。

## 权威身份与 revision

Bridge 接收 `client_profile=cader-cad/1`，在接受请求时固定 operation、输入 document_id、expected_revision 和 source_artifact_id；完成后压缩参数仍保留这些字段。新增受认证的 `GET /v1/requests/{request_id}` 返回身份、原生请求 hash 和 job 快照，旧 job 回包结构保持兼容。

Python 通过这一原生记录核对提交结果，并映射公共 `operation/request_document_id/result_document_id/source_artifact_id`；Python 缓存不是权威来源。相同 Bridge 实例的 journal 尚存时，重启 Python 后仍能对账。实例改变、记录过期、记录缺失或响应身份不符均不能推断成功；客户端冻结写入，不能自动重放。

revision 是数据库事件观察序号。写入先锁文档再检查 expected_revision；失败在 CAD 线程完成事务展开后读取实际 revision。回滚允许 revision 前进；排队阶段等无法读取文档的失败不伪造 revision，保留未知语义。create/reopen 的 revision 属于结果图；失败无结果图时属于输入图。

三类摘要分开使用：Cader 审核计划摘要、精确 `request_json` 审计摘要、原生确定性请求摘要。原生去重算法未改变，摘要都不构成自动重放授权。journal 仍有原来的内存容量与有效期上限；保存件记录也只属于当前 Bridge 实例。

## 文件和独立验收

create 要求现存、规范化、绝对本地 `.cader/artifacts` 目录，逐级拒绝链接/reparse point。save 要求该目录内规范化的完整 `.dwg` 路径，`overwrite=false`；不静默改绑目录。文件保存不是图元事务的一部分，文件失败不会被描述为实体事务已回滚。

保存回包记录源 document_id、revision、SHA-256 和字节数。重开按 artifact_id 验证原文件，创建独立只读图并引用 source_artifact_id；随后分页查询这张新图，而不是复用源图查询作为验收结果。

查询只归一化能够证明无信息损失的规范实体。检查几何、图层/颜色/线型/线宽、可见性、厚度、文字旋转/宽度/倾斜/对齐/镜像/字体及圆/文字法向；无法用本 DTO 完整表示的类型或属性列入 `unsupported_geometry_types`。客户端必须据此拒绝“不完整查询即通过”，不能忽略该列表。

## 复现

在 Cader 构建产物与已审核的固定 fixture 策略均存在、专用 AutoCAD Bridge 已启动时：

```powershell
python scripts/verify_cader_cli.py `
  --cader-root D:\path\AutoCAD_Cader `
  --bridge-dir "$env:APPDATA\Autodesk\ApplicationPlugins\AutoCADMCPBridge.bundle\Contents\Windows" `
  --owned-pid 12345 `
  --output .git\managed-test-new-run
```

脚本先核对 Bridge PID 和 Cader 编译后的 schema，再运行原生故障检查与实际 `cad-test --backend http --authorize-write`。它仅创建临时运行配置、新工作图和新 DWG，不改 Cader 源码/策略，不启动或关闭 CAD；运行者应记录、关闭自己创建的图纸与专用实例。输出目录必须尚不存在；私有原始日志不得未经脱敏公开。

当前通过范围是固定 line/circle/text 计划的真实文件闭环。图片识别、复杂电路重绘、任意字体/样式、多种实体扩展及跨 Bridge 重启的持久恢复不在此轮验收范围。
