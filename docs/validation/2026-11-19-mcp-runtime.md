# MCP 运行时工具、分页与首批绘图实机报告

日期：2026-11-19（Asia/Shanghai）。默认后端仍为 COM。

本轮新增四个 MCP 工具：后端状态、job 查询、原子批处理、分页查询；旧 36 项
schema 保持一致，总数 40。HTTP 另迁移矩形、多段线、单行文字、多行文字和对齐标注。
编辑、图块属性和文件工具尚未迁移，不将其记为完成。

## 结论与证据

修复版 DLL SHA-256：
`11dfad2a309b0ac9e78bbbee05be4972d240843cd60e68bf68c24cff1c6ca5ec`。
使用独立、正常启动的 AutoCAD 2026 实例，实际 MCP stdio 客户端连接 Python HTTP
后端，再由原生 Bridge 在 CAD 主线程执行。没有使用 fake CAD 冒充实机结果。

最终运行的功能检查通过，原始 `qualification.json` 仍保留 `completed=false`：
即时进程检查与异步退出发生竞争。随后独立检查确认自建 PID 52600 已退出、原有
PID 46240 保留，见 [cleanup-recovery.json](runtime-2026-11-19-03/cleanup-recovery.json)。
脚本已增加有界等待并补离线回归，不把收尾问题从历史记录中抹去。

| 验证项 | 实机结果 |
| --- | --- |
| 分页超过旧上限 | 1205 条线，四页 400 / 400 / 400 / 5；坐标全集与预设一致 |
| 身份与重复项 | 1205 个唯一 ID；跨页无重复；切换旧工具绑定后显式文档仍正确 |
| 过滤与字段裁剪 | RuntimeA 图层 603 条；请求 handle 时只有身份字段与 handle，无多余几何 |
| 批处理/journal | 同 ID 同内容返回同一结果；内容冲突被拒绝；job 身份一致 |
| 回滚与 revision | 层/线/失败步骤整体回滚，无残留层或实体；过时 revision 被拒绝 |
| 游标 | 篡改、过滤变化、跨文档被拒绝；图纸修改后旧游标失效 |
| 旧查询兼容 | 超过 1000 项仍明确 RESULT_TOO_LARGE，没有静默截断 |
| 矩形/多段线 | AcDb2dPolyline、预期顶点与闭合状态；保留旧 COM 忽略输入 Z 的语义 |
| 单行文字 | 中文字符串、MCP_CJK、位置、高度 2.5、旋转 30° 重读正确 |
| 多行文字 | 两段中文内容、MCP_CJK、宽 40、高 3 重读正确 |
| 对齐标注 | 起终点正确、测量 10、标注线位于 y=5、z=0 |

完整顶点、文字、包围盒和源文件哈希见
[最终功能结果](runtime-2026-11-19-03/verification.json)；逐调用记录见
[JSONL](runtime-2026-11-19-03/cases.jsonl)。这些是合成测试图形，没有保存或上传私有 DWG。
文字数据/样式重读不等同于所有字体、机器和模板的视觉兼容性验收。

## 失败尝试保留

1. [runtime-01](runtime-2026-11-19-01/qualification.json)：分页 1205 项已通过，
   随后矩形的旧批量 Polyline2d 构造路径触发原生
   `db2dpoly.cpp@352: eInvalidInput`。客户端返回 OUTCOME_UNKNOWN，未重放。
   测试进程退出，原有实例保留，见 [操作记录](runtime-2026-11-19-01/operator-notes.json)。
2. [runtime-02](runtime-2026-11-19-02/qualification.json)：修复版已成功创建五类实体，
   测试错误地要求 DimLinePoint 与输入坐标完全一致。独立只读复查显示测量 10、
   实际点 `[10,5,0]` 位于预期标注线上，见
   [几何复查](runtime-2026-11-19-02/geometry-reinspection.json)。
3. [runtime-03](runtime-2026-11-19-03/qualification.json)：纠正几何等价性检查后
   全部功能通过；收尾竞争及后续独立清理验证如上。未改写三个运行的原始成功/失败标记。

修复采用先将 Polyline2d 父对象加入目标数据库，再逐个 AppendVertex，并在同一事务
登记顶点和关闭 wrapper。原生内部精确根因未经 dump 确诊；实测结果支持这条替代
路径修复了本轮复现的问题，不能推广为永不崩溃。
接口依据见 [Autodesk AppendVertex 文档](https://help.autodesk.com/cloudhelp/2026/ENU/OARX-ManagedRefGuide/files/OARX-ManagedRefGuide-Autodesk_AutoCAD_DatabaseServices_Polyline2d_AppendVertex_Vertex2d.html)。
标注定义点本来允许位于标注线上的不同位置，见
[DimLinePoint 文档](https://help.autodesk.com/cloudhelp/2026/ENU/OARX-ManagedRefGuide/files/OARX-ManagedRefGuide-Autodesk_AutoCAD_DatabaseServices_AlignedDimension_DimLinePoint.html)。

## 离线与复现

- Python：103 passed / 33 skipped；旧契约、四项新工具的实际 MCP 参数/结构化输出、
  HTTP 传输身份、无重放、COM 状态不启动 CAD，以及退出延迟回归均覆盖。
- C#：journal 11、无 UI 消息泵 host 生命周期 12、签名游标 11 项断言通过。
  游标 TTL/跨实例签名在独立测试中覆盖，未声称实际等待十分钟完成原生 TTL 测试。
- 原生 DLL：构建零警告、零错误；验证加载的是上列隔离 DLL，未覆盖用户实例锁定的
  已安装旧 DLL。使用新 HTTP 能力前应按安装说明编译安装，并在新的 CAD 会话加载新版。
- 复现入口、限制和清理检查点见 [绘图迁移说明](../design/http-drawing-migration.md)
  与 [运行时工具说明](../design/mcp-runtime-tools.md)。脚本输出目录必须是新的。

本轮不构成新版 DLL 的长期稳定性或性能验收。既有 CAD-09 测量针对旧 DLL，
不得将其直接当作本版新增工具的性能数据。COM 默认配置未修改。
