# MCP 对 Cader 修订 2 的确认

日期：2026-11-19。Cader 审阅提交：`266c6895048f1ce97a5517265a7f14f29bfa5e1c`。

**MCP 方接受 cader-cad/1、draft_revision=2 作为适配实施基线。** 四项语义意见已获得一致的回应，不再沿用修订 1 的冲突假设。此确认不表示版本化 profile 已实现、双方发布已冻结或真实 DWG 联合验收已通过。

## 精确输入与验证

以下共享文件按原始 UTF-8/LF 字节保存，未重排、重新序列化或修改源 manifest 的 unfrozen 状态：

| 文件 | SHA-256 |
| --- | --- |
| cader-v1.schemas.json | `e239266ee97ccd64284f6a6b5896eb57532b0f18eb5769dad3899e614191dd28` |
| managed-cad-v1.cases.json | `9e33ab75c054e0b49d60c0616914f497d584aa284e7ff3898a643fa50caa0e41` |

共享快照位于 [schemas/cader-cad-v1](../../schemas/cader-cad-v1/configs/contracts/cader-v1.manifest.json)，MCP 确认记录为 [mcp-confirmation.json](../../schemas/cader-cad-v1/mcp-confirmation.json)。快照单独禁用 Git 文本换行转换，保证 Windows/CI 校验相同文件字节；原 Cader 文件未修改。

MCP 离线验证通过：**18 个结构向量、11 个操作身份向量、1 个精确请求审计向量，共 30 项**。另有固定 manifest 与篡改拒绝测试。结果见[机器报告](evidence/cader-v1-revision2-vectors-2026-11-19.json)。这些是合成契约数据检查，不是 MCP 适配代码或 CAD 的执行测试。

## 已确认的语义

1. WorkingBinding 为 managed=true/read_only=false，明确返回绑定的 output_directory；VerificationBinding 为 managed=false/read_only=true/source_artifact_id，只用于查询。
2. revision_mode 使用 observed_database_events。新图可从非零 revision 开始；失败后序号允许前进。MCP 应返回可证明的失败后 revision，Cader 独立核验并结束本轮写入。缺失、倒退、身份错误或无法验证时继续冻结；不重置事件序号，不自动重放。
3. create 显式携带已存在、规范化的 output_directory，回包确认同一目录。save 的完整 output_path 必须属于该绑定目录，禁止覆盖与链接越界。MCP 可附加服务端白名单，拒绝时不能静默改绑目录。
4. job 携带 operation、request_document_id、result_document_id、source_artifact_id。batch/save 对应原工作图；create/reopen 产生新结果图，reopen 匹配保存件。权威 revision 归属于结果图，失败无结果图时归属于输入图。
5. 所有 ID 使用 `^[A-Za-z0-9._-]{1,128}$`；对象 alias 为字符串且仅在所属 document_id 内有效。第一轮只接受图层 0 上的 line/circle/text，不隐式创建图层。

## MCP 确认的转换规则（mapping revision 1）

以下规则是接下来实现 profile 的规范，不是已开放的新接口。保留普通 server 的 44 项工具和现有 HTTP Bridge：

| 公共操作 | 原生 operation / 参数 |
| --- | --- |
| create_working_document | create_working_document；document_id/expected_revision 为 null；units 按下表映射；output_directory 为校验后的规范目录；managed=true 是必须通过的公共断言，不新增原生写权限 |
| execute_atomic_batch | `_batch`；document_id、expected_revision 原样绑定；atomic=true；保持步骤和 ID 顺序；text.point→position，显式 rotation=0；仅图层 0、最多 100 个受限图元 |
| save_document_as | save_document；源文档/预期 revision 不变；先核对 output_path 的目录与已绑定目录一致，再映射为 file_name；overwrite 必须 false |
| reopen_document | reopen_artifact；输入文档/预期 revision 为 null；artifact_id 原样传递；返回只读新文档和同一保存件引用 |

公共单位与原生输入固定映射：unitless→unitless、mm→millimeters、cm→centimeters、m→meters、in→inches、ft→feet。原生返回 code 分别为 0、4、5、6、1、2，转回公共单位字符串。Cader 的 layout 是计划单位，由其在请求前映射为 unitless。

转换必须对相同合法 DTO 产生相同原生请求内容，不能为了恢复请求临时更换 ID、步骤顺序或省略/补充不同默认值。非法路径、非零文字旋转、非规范线型/法向或无法完整表达的实体不得静默丢失信息。

## 三类 hash 与去重

MCP 接受 Cader 对计划审核、请求审计和协议发布摘要的区分：

- 审核计划 hash 仍由 Cader 基于其解析后的计划计算，用于策略审核。
- request_sha256 针对 prepared 中保存的 request_json 精确 UTF-8 字节；MCP 和测试直接校验该字符串，不假设 Python 重序列化等于 JavaScript JSON.stringify。末尾加 LF 会改变摘要，已由测试确认。
- 协议 manifest 固定 schema/examples 的完整文件字节，包括末尾 LF。

原生去重继续以当前 Bridge 实例、request_id 为定位，使用既有 `Journal.Canonical` 对 `{document_id, expected_revision, operation, args}` 计算的 SHA-256 判断内容。对象 key 递归按 Ordinal 排序，数组顺序保留，JSON 字符串编码以现有 .NET 实现为准。request_id 本身是查找键，不在该内容 hash 中。

同一有效窗口内，同 request_id/相同原生签名返回原 job；同 ID/不同原生签名为 REQUEST_ID_CONFLICT。实例重启或 journal 丢失后不承诺去重；记录有界且终态保留约十分钟。公共 DTO 的请求审计 hash 不代替原生签名，也不授予任何重放权限。适配层需要关联公共操作、输入目标、保存件来源和原生 job；不能仅凭当前 Python 进程的临时变量猜测对账身份。

## 尚需 MCP 实现与共同验收

- 显式版本化 profile/入口，严格消费本快照的七项工具 DTO；默认 COM 与普通 server 不变。
- 公共 DTO→既有 HTTP 请求的确定性映射、身份验证、程序客户端需要的错误/job DTO。
- 在原生 CAD 线程记录失败后的权威 revision，并为按 request_id 的查询保留操作及输入/输出身份；不根据提交前值伪造失败后值。
- 查询真正执行实例/revision guard；仅为已验证的规范三图元生成 operation/args，无法表达的属性明确拒绝验收。
- 完成适配器正反例，再在独立、授权的 HTTP CAD 实例中，由 Cader 原生 CLI 执行新建→三图元批处理→查询→保存哈希→只读重开→查询。记录相同 schema/客户端/DLL 版本及进程清理结果。

这些步骤完成后再冻结发布与声明真实 DWG 联合验收。本轮没有启动 AutoCAD、调用模型、切换默认配置或修改 Cader。

离线复核：

```powershell
python scripts/verify_cader_vectors.py
python -m pytest tests/test_cader_contract_vectors.py -q
```
