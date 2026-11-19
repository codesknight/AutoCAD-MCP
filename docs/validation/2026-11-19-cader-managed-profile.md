# cader-cad/1：MCP 实现与真实 DWG 联合验收

日期：2026-11-19。**两轮实际 Cader CLI 固定几何计划均通过绘制→保存 DWG→只读重开→独立查询比较。** Cader 的代码、策略和默认配置未修改；仅为运行创建 `.cader` 下的临时 MCP 配置和产物。

## 版本与环境

- MCP 基线：`4d4b5a7f81d9555a795cee64fb3d7581b3fc6e14`；测试中新增源文件的精确 SHA-256 见[源码指纹](managed-profile-2026-11-19-02/source-hashes.json)。
- Cader：`266c6895048f1ce97a5517265a7f14f29bfa5e1c`，128 个 tracked 文件运行前后逐文件摘要相同；调用其现有编译 CLI，没有重构建或修改代码。
- AutoCAD 2026：`25.1s (LMS Tech)`，专用测试 PID 33564；加载 DLL SHA-256：`dd8321e2aae125354e9cdaa4170873332539c849ff47b1acf45ba239d284a642`。
- 公共契约：`cader-cad/1`、draft_revision=2、mapping_revision=1；schema SHA-256：`e239266ee97ccd64284f6a6b5896eb57532b0f18eb5769dad3899e614191dd28`。先比较 Cader 编译 CLI 导出的 schema，再运行联合测试。
- 普通 MCP 仍为 44 工具，默认 COM；测试显式选择独立 `autocad_mcp.managed_server` 的七工具 HTTP profile。

## 实际执行结果

| 运行 | Cader run ID | CLI / DWG 验收 | 文件字节数 |
| --- | --- | --- | ---: |
| 01 | `managed-e7bad22b-0dc3-457f-a08c-5f8b0d0bf323` | exit 0 / passed | 31988 |
| 02，最终实现 | `managed-f09333e2-623e-4db9-8436-7cf8f5bc9f48` | exit 0 / passed | 31988 |

每轮实际执行八项动作：状态、新建受控工作图、空图查询、直线/圆/文字三步原子批处理、源图查询、保存、重开、验收图查询。使用 Cader 已审核的 `benchmark/fixtures/managed-geometry.plan.json`；`--authorize-write` 明确授权此测试写入。两轮均 execution/saving/reopening succeeded、verification passed，recognition 为 `not_performed`。

最终源图 document_id 为 `a57cd4066301456f99ade1cc907ded1c`，revision 0→16；只读重开图为 `2e892706c2fb46e1b174a6cd614e55c7`，自身 revision 0。两个身份不同；按各自 revision 独立读取并比较实体。

最终产物：`<CADER_WORKSPACE>/.cader/artifacts/joint-mcp-d23cb449da1d47579e54fdcc1836bce2.dwg`，SHA-256：`e55352c93da44148fbc2905e7f42199607740836f5edc0c3a175cc8bc677f784`，31988 字节。测试另行从磁盘计算摘要和大小；仓库不提交 DWG 二进制。

## 故障与对账

两轮原生测试均先插入文字，再以端点间距 1e-12 的直线触发原生几何容差拒绝。事务回滚后实体、图层和文字样式均无残留；权威 revision 从 0 前进到 6。创建新的 Python adapter 仍通过原生请求记录读到相同失败身份和 revision=6，证明结果不是旧 Python 对象缓存补造。

过期 revision 写入明确 `not_executed` 并返回实际 revision。离线测试另覆盖接受写入后丢失响应（仅一次 POST）、记录缺失/身份错误、不支持几何属性、只读写入拒绝、路径规范化和会话关闭竞态；这些离线检查不冒充本轮 CAD 故障注入。

## 检查与边界

- Python：**178 passed / 33 skipped**。跳过项依赖显式实机 opt-in，不计为通过；上述真实 CLI 运行另行执行。
- C#：Journal 17、Host 12、Cursor 11、Artifact 17，共 **57 项断言通过**；正式插件 Release 构建零警告零错误。
- wheel 打包后检查包含独立入口、默认配置和精确 schema 原字节；`jsonschema` 已声明为运行依赖。
- 这是固定三类几何的真实文件闭环，不是图片识别/电路还原、长期稳定性或新版本性能验收，也未声明双方发布已冻结。

## 证据与收尾

| 证据 | 运行 01 | 运行 02 |
| --- | --- | --- |
| 汇总与完整 Cader 回包 | [qualification](managed-profile-2026-11-19-01/qualification.json) | [qualification](managed-profile-2026-11-19-02/qualification.json) |
| 原生调用及故障 | [native calls](managed-profile-2026-11-19-01/native-calls.json) | [native calls](managed-profile-2026-11-19-02/native-calls.json) |
| 原始实体属性 | [entities](managed-profile-2026-11-19-01/raw-native-entities.json) | [entities](managed-profile-2026-11-19-02/raw-native-entities.json) |
| 精确请求审计摘要 | [audit](managed-profile-2026-11-19-01/request-audit-summary.json) | [audit](managed-profile-2026-11-19-02/request-audit-summary.json) |
| 实例清理 | [cleanup](managed-profile-2026-11-19-01/cleanup.json) | [cleanup](managed-profile-2026-11-19-02/cleanup.json) |

公开 JSON 已替换本机工作区路径；token、私有设置和原始精确 request_json 不公开。审计摘要核对的是原始 UTF-8 request_json，展示的脱敏参数并非重新参与 hash 的原文。

清理首次快速 COM 关闭受到 `RPC_E_CALL_REJECTED`，原异常保留；重新观察后仅针对本轮自建图纸进行有界重试，关闭全部图纸并正常 Quit，独立确认测试 PID 已退出且无 acad 进程。本轮没有保留不用的测试实例。

复现命令和接口限制见[使用说明](../design/cader-managed-profile.md)。
