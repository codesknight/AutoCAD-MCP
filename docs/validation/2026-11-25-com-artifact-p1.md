# 2026-11-25 普通 COM 文件交付 P1 第一批

结论：正式提供普通 COM 的受控保存、文件指纹、独立只读重开和指定验收文档查询。两轮真实 AutoCAD 2026 回归各通过房子 48 实体、原始电路 77 实体。默认 COM、原 44 项调用和 47 项工具总数保持兼容；未修改 Cader 代码、权限策略或旧 unknown 屏障。

**本批不是全部 P1 完成，也不是新一轮 Cader 自主绘图验收。** 驱动读取 Cader P0 已验收的两份实际 DWG，校验原摘要，以 InsertBlock/Explode 导入自建工作图后调用生产新接口；不调用模型、不使用简化线圆替代电路。Cader 接入新文件契约后的客户端真实闭环仍待交付。

## 实现及自动检查

- [文件契约](../design/com-file-artifacts.md)：`execute_observed_operation` 增加 save_document_artifact、reopen_document_artifact、query_verification_entities；能力矩阵同步声明，结果与 file_progress 进入已有请求 journal。
- 文件操作与实体事务分离；独占子目录、禁止覆盖、每工作图输出根绑定、DWG 头/SHA/大小检查、只读验收新身份、工作绑定恢复；拒绝篡改、关闭、更名、内存编辑、其他空白未命名文档风险及跨 backend 记录恢复。
- 全量 `python -m pytest -q`：**298 passed / 34 skipped**；34 中包含 33 个原有原生 opt-in 等跳过，以及本机缺 symlink 创建权限的负例。原生效果由下述实机单独记录。六个改动 Python 文件 isolated ruff I/F 通过；47 项普通 MCP / 原有发现兼容断言随全量通过。
- 新增真实内存 MCP 传输往返，验证三项文件操作和 get_execution_status 的 file_result、重复请求不派发；另注入 SaveAs 实际产生文件后丢 ACK、ACK 后文件头无效，分别保留 result_unknown / observation_failed，绝不重放或删除副作用。fixture 头字节不作为真实 DWG 证据。

## 实机结果和失败轨迹

[机器汇总](evidence/com-artifact-p1/summary.json)及每轮 JSON 保留 instance/document/request/ACK/失败阶段，不提交私人 DWG、截图或原生全实体内容。私有原始 qualification 的 SHA-256 随脱敏文件保留。

| 轮次 | 自建 PID | 结果 | 清理 |
| --- | --- | --- | --- |
| [native-01](evidence/com-artifact-p1/native-01.json) | 25444 | 独立几何读取对不支持属性反复重试而中止，未完成验收 | 后续核对 owned_pid 后强制关闭，仅此自建实例 |
| [native-02](evidence/com-artifact-p1/native-02.json) | 34428 | SaveAs 已通过；Open 已 ACK，但文档集合变化，observation_failed | 正常 Quit 被拒；核对后强制关闭自建实例 |
| [native-03](evidence/com-artifact-p1/native-03.json) | 77672 | 改唯一文件名及有界观察后仍集合不符，保留失败，不重复 Open | 同上 |
| [native-04](evidence/com-artifact-p1/native-04.json) | 76764 | 48 / 77，两例文件及几何/文字读回通过 | 正常关闭自建图并 Quit，OS 确认退出 |
| [native-05](evidence/com-artifact-p1/native-05.json) | 19172 | 最终代码复测：48 / 77，两例通过 | 正常关闭自建图并 Quit，OS 确认退出 |

独立驱动只在自己的新进程内先核对并关闭自动空启动图。native-04/05 在该条件下通过；早期集合变化的唯一根因未确证，不能归咎于文件名一项。生产入口没有放宽原集合守卫，而是在其他空白未命名文档存在时于 Open 前拒绝；不会代关用户图。新文件名与五秒只读观察均不意味着重试 Open。

最终 native-05：

| 用例 | 原输入 SHA-256 | 新保存 SHA-256 | 新文件字节 |
| --- | --- | --- | --- |
| final_house | `82fe4d93c71e43367a2e919b7f1e67b95315d1bea9c0e3395519394a96ebb2ff` | `3a102e42e40c326c67fae8e8d2a2a925f976d11adfd71bb473c9c402f3a28249` | 24483 |
| original_circuit | `6a05acb30485adfc42c51bd5731acad3cdfb3857eccb9e2e94a80c6f09479faf` | `9c225aeda00d691389366ae51c73072754f4615a0d0196fa47484d2773f5e043` | 23163 |

每例新文件和验收副本 SHA/大小一致、实际 ReadOnly、验收 ID 独立、工作绑定 ID 不变；原输入文件前后摘要相同。独立 native 快照读取实体类型/图层/颜色及实际支持的点、坐标、文字、高度、旋转、面积和填充字段，以七位小数规范化排序比较，不要求 ObjectID 相同。它不宣称完整任意 DWG 语义等价，也不重新证明源手稿语义；源语义验收属于 Cader 先前报告。

运行前已有 PID 48984/49292/59304，最终仍仅这三进程存在，未调用其 Close/Quit；所有本批自建 PID 已退出。21 份既有用户改动文件摘要保持一致，未混入提交。本驱动不调用打印/截图接口；未独立测量其他进程每个打印参数，不能扩展为任意打印状态验收。

## 复现与后续

在 Windows/AutoCAD 2026、已安装项目依赖及具有上述已验收 Cader P0 私有 run 的环境中，指定全新输出目录：

```powershell
python -m scripts.verify_com_artifact_p1 --cader-root D:/path/AutoCAD_Cader --output D:/new-test-output
```

驱动使用 DispatchEx 且核对进程不是运行前已有 PID；输出 qualification.json、完整请求 calls.json、新文件及验收副本，不覆盖旧轮次。正常退出仅清理自建实例中的测试文档；发现意外外部路径即拒绝清理。此脚本依赖已验收 P0 run，不能在没有私人原始输入时以 fixture 冒充复现。

后续 P1：Cader 根据能力发现接入上述三操作，再运行原始房子/复杂手稿，提交客户端请求关联和独立 verifier 结果；MCP 继续补字段投影/候选实体定位及真实校准的截图证据。当前 query 的 legacy_summary_partial、COM 无权威 revision、无持久化跨进程 journal、无像素映射及默认多实例 ROT 选择限制均明确保留。
