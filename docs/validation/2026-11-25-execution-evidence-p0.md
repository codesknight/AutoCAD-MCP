# 执行证据 P0：实现、故障验收与 Cader 联合回归

日期：2026-11-25。**MCP 首批 P0 实现及限定范围的 COM/HTTP 故障验收通过；复杂手稿联合验收未通过。** 房子任务通过，原始复杂手稿两轮失败分别保留，不以简单几何故障夹具替代它们。

## 实现范围

普通入口从 44 增至 47 工具，原 44 项工具的参数和成功内容保持兼容，默认仍 COM。三个新增显式入口为 `get_document_binding`、`execute_observed_operation`、`get_execution_status`。能力矩阵、内部 CAD 参数示例、回执字段及保证范围见[接口说明](../design/execution-evidence.md)。独立 `cader-cad/1` 七工具入口不变。

- COM 用 canonical IUnknown 的生命周期身份区分文档，名称/路径只是标签；SaveAs 保留当前身份，关闭/重连不能继承旧身份。实体读取/编辑还核对所属文档，防止跨数据库 ObjectID 被当作当前文档实体。
- COM 新执行入口登记请求后只派发一次，保留逐个原生动作 ACK，将无 ACK 和 ACK 后观测失败分开。纯 ObjectID 读取失败不会在新入口自动引入 Delete 补偿写入；已知实体集合与完整性分列。
- COM 回执仅覆盖能力声明中的十项操作，且只允许写入本连接创建的工作图。其他旧操作未获得同等回执；没有权威 COM revision、跨 Python 重启的 journal、原子批次或普通路径只读重开保证。
- HTTP 复用既有原生 request records。冷客户端直接核对健康身份并读取 journal，不再先等待 CAD 主线程 `/status`。缺失/过期/错身份都不证明可以重放。

## 代码检查

| 检查 | 最终结果 |
| --- | --- |
| Python 全量离线 | **276 passed / 33 skipped**，跳过项不计为实机通过 |
| 执行证据专项 | 30 项，覆盖身份、参数、只读/非托管拒绝、ACK/无 ACK、冲突/延迟、过期/重启及实际 MCP 派发 |
| C# Journal / Host / Cursor / Artifact | 17 / 12 / 11 / 17，共 **57 项断言通过** |
| NativeTests Release 构建 | 零警告、零错误 |
| 改动 Python 静态检查 | isolated ruff I/F 通过 |

普通接口发现测试逐项保留原 44 项 schema，并单独校验新增[三个工具快照](../../tests/fixtures/mcp-execution-tools-v1.json)。[源码指纹](execution-evidence-2026-11-25/source-fingerprints.json)使用 CRLF→LF 后的 SHA-256；原生 DLL 另记录实际文件摘要。

## 真实 COM 故障与身份验收

最终运行 [com-05-final](execution-evidence-2026-11-25/com-05-final/qualification.json)，[完整调用](execution-evidence-2026-11-25/com-05-final/calls.json)。测试通过进程专属 NativeTests ROT 标识绑定自建 PID 32216，避免多个 AutoCAD 的重复 application moniker 总是返回首个进程；该定位能力仅属于显式测试插件，不是产品默认实例选择机制。

| 条件 | 实际结果 |
| --- | --- |
| 两张不同目录的同名 `same.dwg`、SaveAs | 文档 ID 不同；各自 SaveAs 后生命周期 ID 不变 |
| 激活另一张同名图 | 原绑定写入在原生调用前拒绝，没有画到另一张图 |
| 外文档实体 ID | 移动在原生写前拒绝，外文档实体坐标不变 |
| 实际创建、查询、移动、删除 | 返回匹配文档的 created/modified/deleted 集合 |
| 真实 AddLine 返回被测试钩子抑制 | 原生副作用存在、无 ACK；结果保持 unknown，不重放 |
| ACK 后绑定读取被钩子拒绝 | observation_failed，保留 ACK 和已知 ID，不改成未执行 |
| ACK 后实际 CAD 主线程固定阻塞五秒 | 最终原生属性读取等待后成功，只有一次 AddLine；不强求 CAD 产生并未出现的 HRESULT |
| 新建 Python backend 后查询旧请求 | unresolved、replay_safe=false，不接管旧工作图 |

适配层返回/读取钩子和真实五秒原生阻塞分列，前两者不是 AutoCAD 崩溃或伪造原生 HRESULT。外部激活和原生编辑用于模拟同类人工事件，不声称有人逐点手工操作。

历史试跑全部保留：[com-01](execution-evidence-2026-11-25/com-01/qualification.json)通过；[com-02](execution-evidence-2026-11-25/com-02-native-busy/qualification.json)在真实阻塞时遇到 pywin32 `<unknown>.ObjectID` 包装错误，测试强求 HRESULT 而失败；改用原生属性读取后，[com-03](execution-evidence-2026-11-25/com-03-native-busy/qualification.json)等待后成功，旧测试仍强求失败而被拒绝。修正验收标准后 [com-04](execution-evidence-2026-11-25/com-04-native-busy/qualification.json)与最终运行通过，没有把历史失败改写为成功。

## 真实 HTTP 故障验收

[http-02-final](execution-evidence-2026-11-25/http-02-final/qualification.json)及[逐项证据](execution-evidence-2026-11-25/http-02-final/cases.json)通过；[首轮结果](execution-evidence-2026-11-25/http-01/qualification.json)也保留。正式 Bridge DLL 与既有受控 DWG 验收使用相同文件摘要，未增加生产故障注入端点。

- 实际 POST 转发至 Bridge 后丢弃响应：写请求只有一次；按原 request_id 对账并独立查询，只有一个预期实体。
- 五秒原生主线程阻塞期间，完全新的 Python 客户端仍能读取已完成请求；新请求为 queued，客户端超时保持未知；解除阻塞后只读查询原请求确认延迟完成，没有重发。
- 将实际读取的原生记录在传输边界篡改为错 request/document/instance 或缺失身份：客户端均拒绝，写请求数为零。篡改不发生在 CAD 数据库，原记录未改。
- 外部 COM 原生编辑触发 revision 前进；旧 revision 写入被拒绝，数据库仅有三条预期线。
- 查无记录返回 unresolved，不解释成从未执行。只重启自建实例的 Bridge 后，旧 instance_id 失效，新 journal 查不到旧请求，也不授权重放。

本轮的重启覆盖 Python backend 和 Bridge 服务；没有把它称为新的 CAD 进程终止/重启验收。此前 CAD 进程重启故障另见 [CAD-09 报告](2026-11-19-cad09.md)。

## 实际 Cader CLI 联合回归

使用原有构建 CLI、真实模型及真实 AutoCAD，模型自主选择旧 MCP 动态工具；没有改 Cader 代码、策略或默认配置。227 个 tracked 文件前后摘要相同。本轮没有给 Cader 自动接入新回执，新 API 与旧路径兼容回归必须分开看待。

| 任务 / run ID | 结果与限制 |
| --- | --- |
| 红屋顶、蓝墙、小房子、大树、儿童绘本；`quality-68d8598c-efe9-406b-9e7d-8a76e18041e8` | CLI exit 0；质量、主动视觉、实际图像请求及一次任务授权均通过；34 次确认、0 unknown。该原任务未要求 DWG 保存，artifact=null，不能称作新增 DWG 重开验收。[汇总](execution-evidence-2026-11-25/house-summary.json) |
| 原始复杂手稿；`quality-4c795262-f31c-4732-9b76-6d4d0c31753c` | 初次检查文字等通过，但拓扑失败：同一直线位置存在重叠区段。修正期间 delete_entity 被文档守卫拒绝；旧路径没有完整匹配回执，Cader 保守记为 unknown 并冻结。最终 89 次确认、1 unknown，未完成保存/源图拓扑验收。[汇总及重叠坐标](execution-evidence-2026-11-25/circuit-summary.json) |
| 同一原始手稿，显式绑定自建实例的新任务；`quality-b492811a-6a58-48d6-bed4-a0d14a98c518` | 在源器件 inventory 阶段报 SOURCE_COMPONENT_INVENTORY_FAILED，0 次 CAD 写入，未授权绘制。不是对前一任务的恢复或重放。[汇总](execution-evidence-2026-11-25/circuit-isolated-03-summary.json) |

两次手稿都沿用此前原任务的九处数值和底部回线确认；不是无辅助 OCR。隔离任务开始前的两个运行配置因路径在 Cader 工作区外被正确拒绝，随后只在其私有 `.cader` 创建运行配置；[第一次拒绝](execution-evidence-2026-11-25/circuit-isolated-configuration-refusal.json)与[第二次拒绝](execution-evidence-2026-11-25/circuit-isolated-02-configuration-refusal.json)保留，未改配置校验规则。

复杂手稿失败期间，启动时存在的 PID 33272 后续被观察为已退出；退出原因未确定，针对该时段的 Application Error/Windows Error Reporting 未找到对应 acad 事件。本轮未向该 PID 发出 Quit/终止命令。其原保存文件仍存在，但进程退出后不能再独立查询原内存图纸；不能据此宣称完整会话的原图状态已验收不变。COM 首轮测试范围内的原文档前后指纹一致与这一后续环境变化分别记录。

## Cader 接入反馈与未完成验收

1. 根据能力矩阵按操作选择新入口，提交前持久化 request_id，核对 instance/document 与 ACK/观测阶段；不要继续仅按名称或旧错误文本决定是否可写。首批白名单未覆盖全部复杂手稿工具，未覆盖者继续保守处理。
2. 同步更新其固定的 `legacy_COM_name_guard` / `documents=[]` 诊断说明，消费明确的缓存标签、生命周期身份和 unsupported revision；不把 HTTP 保证套到 COM。
3. 对重叠导线，在计划/批次前检查相同轴线的重复区段，修改后仍由实际实体查询和独立拓扑 verifier 验收；不能只放宽计数或重叠门槛。
4. 源器件 inventory 未形成一致有效报告时继续在 CAD 前阻断，改善模型报告装配与反馈；不由 MCP 决议源图语义或增加 OCR 兜底。

旧 unknown 与执行日志保留，[三处屏障文件摘要未改变](execution-evidence-2026-11-25/barrier-preservation.json)。COM 原有请求没有新 journal 记录，不能追溯补造完整回执，也不能以本轮新入口测试通过解除旧屏障。下一次完整复杂手稿/DWG 验收仍需 Cader 团队接入并复测。

## 收尾与复现

自建实例的剩余图纸均核对为本轮无路径的测试图，几何与记录一致后关闭并正常 Quit；独立 OS 复核确认 PID 32216 已退出，无剩余 acad 进程。[清理记录](execution-evidence-2026-11-25/cleanup.json)。首次清理因预期名称列表过窄，在关闭任何文档前拒绝；重新只读核对真实创建序号和几何后执行，[拒绝记录](execution-evidence-2026-11-25/cleanup-first-refusal.json)保留。用户已有 21 个未提交文件摘要未变，未混入提交。

复现专用原生故障时先正常启动新的独立 AutoCAD，显式 NETLOAD NativeTests 并由操作员处理安全提示，再启动 Bridge。以下脚本只定位 PID，不能用于接管用户实例：

```powershell
python -m scripts.verify_execution_com --expected-pid <PID> --native-fixture --output .git\new-com-run
python -m scripts.verify_execution_http --owned-pid <PID> --bridge-dir <PRIVATE_BRIDGE_DIRECTORY> --output .git\new-http-run
```

进程专属 stdio 测试入口为 `python -m scripts.serve_native_test_instance --pid <PID>`，仅用于隔离 Cader 回归；产品使用普通 server 或明确选择的 managed_server。测试输出目录必须不存在。原始 Cader 审计、模型记录、图像和凭据保持私有，公开摘要引用原文件 hash，不重算脱敏内容冒充原始审计。
