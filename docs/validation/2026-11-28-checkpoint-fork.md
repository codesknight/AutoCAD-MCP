# 2026-11-28 检查点恢复协同交付

状态：**MCP 候选实现和真实大图的新基线 API 回归完成；原 attempt17 续绘、旧账本映射与模型最终验收未通过验收。** 不把后者描述为接口测试成功的附带结论。

实现见[版本化契约](../design/checkpoint-fork.md)。普通 COM 新增 fork_checkpoint / get_checkpoint_snapshot 两个 operation，复用显式请求、原 journal、身份和文件验证；保留 47 项工具及原 44 项 schema/成功结果。COM 默认不变，HTTP 不声称支持此协议。Cader 代码、旧任务/屏障未修改。

## 原始输入事实

用户提供的 DWG `complete-sheet.dwg`：630383 字节，SHA-256 `640f55145281acb2f2a0d5e9f12f18f5662d331da39976c78358f03ecc493c19`。

`pause-fresh-native17.json`：3325603 字节，原始字节 SHA-256 `1911cb835888ade10bc1904ad070755b9ce96704118e3ee2113a40a6c8cab7ef`。含 3014 个实体：AcDb2dPolyline 2928，AcDbText 86，quality_accepted=false。**全部 3014 项没有 Handle**；文字缺对齐点/方式、样式及倾斜等字段，多段线缺逐段 Widths 等信息。它是旧摘要格式，不是新快照协议。

原执行 JSONL：149670884 字节，SHA-256 `c86b9bbaad7953dd2263df5a54c596f9adf4261fb8202e7bf3acd927a794429c`。登记的 writer PID 269720 / CAD PID 294120 当前均不存在；这不等于账本全部 unknown 自动消失。本轮不重写账本或授权原任务恢复。

输入预检脚本只读，无模型、无 CAD、无写授权：

```powershell
python -m scripts.audit_checkpoint_inputs --dwg <absolute-dwg> --snapshot <original-json> --ledger <original-jsonl>
```

它输出原字节摘要、类型和缺 Handle 数，并对旧快照给出 CHECKPOINT_SNAPSHOT_CONTRACT。不能靠重命名字段或刚读取的 Native 属性补造历史冻结证据。

## 自动及原生验证

全量 **342 passed / 34 skipped**；新增 25 项检查点 fixture/传输测试，包含真实内存 MCP 请求及 get_execution_status、重复请求不派发、Python journal 丢失后一次性 claim 拒绝再次消费，真实 Windows share-read 锁拒绝另一个写句柄、实际存活 PID 拒绝。其他负例含源/证据/快照 hash、缺字段/Handle、重复 ID、二义 Handle、额外实体、字段变化、路径跳转/越界、unknown、Open 副作用后丢 ACK、返回路径/只读状态错配；失败不授予 owned，不删除副作用。后置绑定失败还会撤销刚登记的权限，并将已记录 file_result 标记 managed=false/binding_valid=false。缺 symlink 创建权限的既有跳过不冒充测试通过。

改动 Python 文件 ruff I/F 通过。仅更新新增于 P0 的 execute_observed_operation 描述基线以说明两个新 operation，旧 44 项及参数 schema 不变。

[脱敏机器结果](evidence/checkpoint-fork-20261128/summary.json)区分四个实机轮次：

| 轮次 | 自建 PID | 结论 |
| --- | --- | --- |
| readonly-01 | 624 | 原始大图的字节副本只读探测遇 RPC_E_CALL_REJECTED，未完成；正常清理 |
| readonly-02 | 30472 | 等待空启动图关闭后的空闲状态，完整读取原始大图 3014 实体，源 hash 不变；正常清理 |
| fork-01 | 38128 | 生产恢复入口复制/Open 已 ACK，后续原生读取遇忙，observation_failed；保留副本/claim/回执，不授予 owned；独立驱动正常清理自己的实例 |
| fork-02 | 24604 | 给只读 Item/GetBulge/GetWidth 调用增加有界读取重试、先检查 CAD 空闲后，独立新授权回归通过；正常清理 |

fork-02 实际使用原始 3014 实体 DWG 和 **readonly-02 新采集的完整快照**，生产 fork_checkpoint 完成真实复制、指纹、可写独立新文档、两次完整 Native 读取及一一映射，旧/新 ObjectID 各 3014 个唯一值，mapping SHA-256 `1ad8fe0d219c870409c1332cc9b08ed8fb2bba603df9acdf9e2362cda1be491e`。源文件不变，quality_accepted=false。没有直接 COM 打开后在测试脚本里赋 owned，权限登记由生产校验路径完成。

**此映射的旧 ID 来自新的只读观察，未证明与 attempt17 执行账本旧 ID 的对应关系。** 未运行真实模型的“只补缺失内容”或最终源图验收，没有用简单图形、DTO、文件能打开或新基线匹配替代历史续绘验收。

原始失败及完整请求/映射保存在私有 `.git/checkpoint-20261128`，公开仅提交摘要/请求 ID/阶段/动作 ACK，避免提交私人 DWG 和实体内容。副本/claim 不自动删除。此次启动前没有 acad，四个自建 PID 最终均不存在；只关闭本轮自建实例。源文件、冻结 JSON、原 JSONL 的前后摘要一致。

## 交给 Cader 的下一步

1. 对齐本地审核授权和一次性 claim 的职责。任意客户端 `unknown=false` 不能替代旧账本对账；空/缺失 journal 不提供恢复许可。
2. 未来保存后调用 get_checkpoint_snapshot，持久化 Handle 与该版本全部字段、source 指纹、请求关联和 snapshot_sha256，避免下一次再次丢失历史绑定。
3. 对当前 attempt17，先确定可审计的旧 ObjectID 到新 Native 身份恢复依据，或明确由用户审核建立新恢复基线。该决定必须保留旧冻结证据，不能把新观察伪装成保存时记录，也不能自动解除 unknown。
4. 接入通过后再建立新任务实例、累计成本/预算并仅继续缺失内容，最后执行原始整图高清/覆盖/残差/连接检查、保存与独立 verifier。模型任务和独立 verifier 最终通过前，本 PR 保持协同候选状态。
