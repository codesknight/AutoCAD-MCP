# 受控工作图、扩展批处理与 DWG 保存重开验证

日期：2026-11-19。基线 `841d120`。只修改 AutoCAD-MCP，COM 默认配置不变，Cader 未修改。

## 实际结果

| 层级 | 结果 | 边界 |
| --- | --- | --- |
| Python 离线回归 | 125 passed / 33 skipped | 含真实 stdio schema 发现；跳过项不是 CAD 通过 |
| 旧 MCP 契约 | 原 36 项 schema 保持；共 44 项工具 | 新运行时 schema 单独保存在 v0.2 fixture；v0.1 历史快照保留 |
| .NET 构建 | AutoCAD 2026 程序集；零警告、零错误 | 构建本身不证明原生行为 |
| 纯 C# 断言 | Journal 11、Hosting 12、Cursor 11、Artifact 17，共 51 项 | 不依赖真实 CAD 的路径/不覆盖/哈希校验与原有契约 |
| 原生 MCP→HTTP→CAD | 42 次调用全部符合预期，其中 11 次为预期错误 | 一轮合成 fixture，不是长时间稳定性或性能基准 |
| 清理 | 自建 PID 57436 已退出，无剩余 acad 进程 | 没有原有 CAD 实例；未操作用户工程图纸 |

测试 DLL SHA-256：`5023de565ca2fa033e1948dd7d9dd3f5dd8cd03182dcf4a3f84813fb36e65a2c`。
用户手动处理 NETLOAD 安全确认后启动 Bridge。测试只使用自建空白文档与本轮输出目录。

## 实机覆盖

1. 发现受控文档、九种批操作、文件操作和不覆盖能力清单。
2. 创建指定毫米单位、绑定输出目录的工作图，返回身份/revision/权限；不改变旧工具绑定。
3. 对已完成的已知请求进行显式去重测试，创建和保存均不产生重复副作用；不是未知结果重试。
4. Python 和原生服务器分别拒绝错误 instance_id；创建未进入错误实例。
5. 混合九种操作在首步、中间和末步失败，均回滚；独立读取确认模型空间为零、图层和文字样式与初始目录相同。
6. 九步成功事务创建图层及八个实体：线、圆、圆弧、矩形、多段线、单行文字、多行文字和对齐标注。分三页读取，重读圆弧长度/角度/法向、中文、文字旋转、图层颜色及标注测量值。
7. 过期 revision 被拒绝；输出路径越界和覆盖现有 DWG 被拒绝。
8. 保存件路径、SHA-256、字节数与实际磁盘文件一致；保存成功后只读重开得到新 document_id。
9. 使用新文档分页查询，忽略跨文档 alias/handle/bounds 后，规范化几何、文字和属性与源图一致。没有用源工作图查询冒充保存件查询。
10. 拒绝写入重开图纸及保存普通初始文档。随后源工作图再画一个圆，源为 9 实体、重开图仍为 8，验证两者独立。
11. 人工修改另一份本轮保存件，重开被 ARTIFACT_CHANGED 拒绝；未知 artifact_id 被拒绝。

原始实机调用、结果和源文件指纹见 [本轮证据](controlled-documents-2026-11-19-01/qualification.json)、[调用日志](controlled-documents-2026-11-19-01/calls.jsonl)、[源文件哈希](controlled-documents-2026-11-19-01/source-hashes.json)。公开副本将本机工作区路径替换为 `<WORKSPACE>`，不含令牌、用户原图或模型输入；未上传 DWG 二进制。

清理时所有三张测试图纸正常关闭；随后 COM 对象不再暴露 Quit。保留此收尾异常，观察空的开始页后通过 Alt+F4 正常退出，独立确认 PID 消失。详见[清理记录](controlled-documents-2026-11-19-01/cleanup.json)。该异常不改写成文件/绘图失败，也不忽略最终进程核对。

## 复现

先按项目安装说明构建插件，在独立空白 AutoCAD 中 NETLOAD，手动处理安全提示，再执行 MCPBRIDGE_START。记录已有 PID 与本轮自建 PID，禁止把原有工程实例作为测试实例。

```powershell
python -m pytest -q
dotnet run --project plugin/AutoCADBridge.ArtifactTests -c Release
python scripts/verify_working_documents.py --bridge-dir '<Bridge DLL 与私有设置所在目录>' --owned-pid <自建PID> --output '<全新结果目录>'
```

脚本读取私有设置，只将令牌传入测试子进程；不打印或写入报告。它不启动或清理 CAD，不修改默认配置，不重试未知写入；操作员在最后仅关闭本轮实例。输出目录必须全新，失败记录不会被覆盖。fixture 对真实模型空间、图层/样式及保存件做检查，不调用图像模型。

## 未据此宣称的能力

- 不是图片识别、图片重绘或 Cader 写入能力验收。
- 未迁移旧 save_drawing/export_current_view、编辑或图块属性操作。
- 文件与数据库事务不构成整体原子操作；文件异常仍可能结果未知。
- 实例重启后文档、artifact 和 job 内存记录不可恢复；JOB_NOT_FOUND 不能证明没有写入。
- 没有复跑此前 30 分钟稳定性/性能矩阵；此前数据不冒充本 DLL 的长期测试。
- 几何/文字字段比较不等同于全图视觉、字体、代理对象或任意 DWG 的通用验证。

接口、权限与恢复语义见[受控工作图契约](../design/controlled-working-drawings.md)。
