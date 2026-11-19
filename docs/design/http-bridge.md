# 实验性 .NET Bridge 与 HTTP 后端

更新日期：2026-11-19。依赖 backend foundation（PR #30），默认仍为 COM。

## 安装与支持范围

本机用户级 .NET SDK **8.0.428** 已安装在 %USERPROFILE%\.dotnet\dotnet.exe。
从 Microsoft release metadata 获取安装包，解压前核对官方 SHA-512。
本机 acdbmgd.runtimeconfig.json 指定 .NET 8，因此插件目标为 net8.0-windows；
不同更新版本需按 [Autodesk 兼容表](https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-Customization/files/GUID-A6C680F2-DE2E-418A-A182-E4884073338A.htm) 核对。

| MCP 工具 | HTTP 支持 |
| --- | --- |
| new_drawing | 创建 Bridge 管理的空白文档，兼容原名字字符串 |
| draw_line / draw_circle | WCS 三元组、图层及有限几何参数检查 |
| create_layer / list_layers | 图层创建、颜色及列表 |
| query_entities / get_entity | 模型空间、类型过滤、摘要、Handle |
| draw_rectangle / draw_polyline | 旧重量级多段线类型，OCS XY 与目标数据库 elevation |
| draw_text / draw_mtext / add_dimension | CJK 文字及共同 WCS Z 平面的对齐标注 |
| get_backend_status / get_job_status | 实例/文档/能力和 job 查询，不重放 |
| execute_atomic_batch / query_entities_page | 显式文档事务与过滤/投影/签名游标 |
| 其他 CAD 工具 | 明确不支持，不回退到 COM |

旧 36 项 MCP schema 保留，新增四项运行时工具，总数 40；资源目录和 VQA 不依赖 CAD 后端。
原子批处理可通过 execute_atomic_batch MCP 工具调用，显式绑定文档并返回完整 job。
图块、变换、区域查询、保存/导出尚未迁移；首批绘图的兼容限制见 [迁移说明](http-drawing-migration.md)。

~~~powershell
.\scripts\install-bridge.ps1 -AutoCADDir "D:\LiuYanhong\Apps\AutoCAD2026\AutoCAD 2026"
~~~

脚本优先选用户级 SDK，避免误用仅有 runtime 的系统 dotnet host。
引用 AcCoreMgd/AcDbMgd/AcMgd，Copy Local=false，不分发 Autodesk DLL。
安装目录为 %APPDATA%\Autodesk\ApplicationPlugins\AutoCADMCPBridge.bundle\Contents\Windows。
脚本核对包 ProductCode，拒绝覆盖非本项目同名包。DLL 被当前实例锁住时，关闭加载它的测试实例再替换；
复制失败不能声称新版本已加载。

包声明 LoadOnAutoCADStartup=false；Initialize() 即使被调用也不会启动监听。
普通启动 AutoCAD 后 NETLOAD 选择 DLL，再执行 MCPBRIDGE_START。
未签名开发 DLL 可能需要用户核验后手动“加载一次”；不自动处理安全确认，也不关闭 SECURELOAD。
另外两个命令为 MCPBRIDGE_STATUS / MCPBRIDGE_STOP。

## 配置与认证

Python 使用 AUTOCAD_MCP_CONFIG 选择独立配置，见
[http-config.example.json](../examples/http-config.example.json)。
backend=http 选择 CAD 后端；server --http 只选择原有 MCP Streamable HTTP 传输。

| 服务 | 默认端口 |
| --- | --- |
| CAD Bridge | 8765 |
| MCP HTTP | 8931 |
| Web UI | 8000 |
| 可选 VQA | 8933 |

令牌至少 32 字符；Python 从 http.token_env 读取，默认 AUTOCAD_BRIDGE_TOKEN。
AutoCAD 优先读取进程环境 AUTOCAD_BRIDGE_TOKEN / AUTOCAD_BRIDGE_PORT。
桌面/COM 启动不会继承后来设置给 Python 的环境；环境令牌缺失时，
可读取 DLL 同目录私有 bridge-settings.json：

~~~json
{"token": "<本机随机令牌，不提交仓库>", "port": 8765}
~~~

文件不超过 8 KiB，不包含模型 API Key。验证脚本生成临时令牌，结束恢复/删除文件。
不要把真实令牌复制到配置样例、聊天或日志。

~~~powershell
$env:AUTOCAD_MCP_CONFIG = (Resolve-Path "docs/examples/http-config.example.json")
# 在本地 shell 设置与 AutoCAD 侧一致的 AUTOCAD_BRIDGE_TOKEN
python -m autocad_mcp.server
# 或供既有 Web UI 连接：
python -m autocad_mcp.server --http
~~~

## 协议与执行约束

端点：GET /v1/health、/v1/capabilities、/v1/status、/v1/jobs/{request_id}；
POST /v1/execute、/v1/batch。
网络线程只解析/认证/排队，CAD 操作在主线程 Idle 执行。不存在任意命令/脚本/反射接口。

- 仅监听 127.0.0.1；验证 Host/port、Bearer、Origin，请求体上限 1 MiB。
- 每个加载文档独立 session ID。只写 Bridge 创建的文档，已有图纸只读；
  请求绑定文档，切换活动图纸不改变目标，关闭后旧 ID 失效。
- HTTP object_id 是文档会话内兼容别名，**不能与 COM ObjectID 混用**。
  另返回 Handle；身份由实例、文档会话与 Handle 共同限定。
- 数据库修改事件使 revision 保守递增，包括回滚中的事件；
  尚未证明覆盖所有手工编辑及特殊对象的强一致性。
- 批处理 1–200 项，只允许 create_layer/draw_line/draw_circle，
  一次文档锁和顶层事务；失败整体回滚。文件/跨文档副作用不在原子承诺内。
- journal 上限 2048，相同 ID+规范化内容去重，不同内容冲突；进行中不逐出，
  终态保留十分钟并释放请求体。没有持久恢复，不承诺跨实例 exactly-once。
- POST 202 后只轮询 job。写响应丢失、轮询失败、实例/文档身份不符返回 OUTCOME_UNKNOWN；
  不重发，不回退；需要重读校验。
- 旧模型空间查询最多 1000 项，超出明确报错；新增 query_entities_page 每页最多 1000 项，支持类型/图层/字段裁剪及签名游标。布局查询尚未实现。
- HTTP 停服/释放在后台完成，主线程不等待网络异步释放。
  原生事件和退出边界捕获异常，本地日志为 %LOCALAPPDATA%\AutoCAD-MCP\Logs\bridge.log，1 MiB 轮换。

协议 schema 见 [schemas/bridge/v1](../../schemas/bridge/v1/)。

## 2026-11-18 初次验证与事故记录

~~~powershell
python -m pytest -q
& "$env:USERPROFILE\.dotnet\dotnet.exe" run --project plugin/AutoCADBridge.ContractTests -c Release
& "$env:USERPROFILE\.dotnet\dotnet.exe" run --project plugin/AutoCADBridge.HostingTests -c Release
# 先普通打开一个 AutoCAD：此脚本只连接，不创建 CAD 进程。
python scripts/verify_http_bridge.py
~~~

Python 离线 77 passed / 33 skipped；C# journal 断言 11 项、无 UI 消息泵的三轮启停断言 12 项通过。
插件构建零警告零错误。实机覆盖七项工具、认证、去重/冲突、事务提交/回滚、revision、
文档绑定，以及真正 MCP stdio 和 Streamable HTTP 创建后重读链路。
最终 completed=true，监听关闭，四张测试图纸关闭。证据见
[验证 JSON](../validation/2026-11-18-http-bridge.json)，其中记录实际测试 DLL SHA-256。

开发中确有失败，不能将其写成全程稳定：

1. 自动化激活出现 e0434352；Windows 记录 ODISSDK.dll 访问异常，Autodesk wrapper 记录加载失败。
   先前依据普通 dump 模块列表未列 Bridge 就断言未加载，证据不足，已纠正。
2. 用户确认普通桌面启动正常。脚本改为 attach-only，不再通过 Dispatch 自动创建实例。
   自动化启动路径尚未验收，没有擅自修改 Autodesk 系统组件。
3. 旧插件同步停服阻塞收尾；改用 EmbeddedHttpHost 后台停止/释放，
   独立测试证明不需要 UI 消息泵，最终实机停服亦通过。
4. 新 DLL 的未签名确认阻塞 NETLOAD；用户手动“加载一次”后完成最终验证。
   当时右侧 CER 窗口创建于 19:02，而当前实例 19:10 启动，不能据旧窗口断定当前 DLL 再次崩溃。

验证脚本只关闭自己新建的空白图纸、恢复原活动文档、停止监听，保留原有实例。
助手自行启动的测试进程另记录 PID，无用户内容才关闭。本轮测试实例最终已关闭。
未上传原始 crash dump，未重置 CAD 配置或改变安全加载策略。

## 后续

2026-11-19 的故障与性能证据见 [CAD-09 报告](../validation/2026-11-19-cad09.md)；新增 MCP/分页/首批绘图及其真实失败、修复、清理复核见 [运行时工具报告](../validation/2026-11-19-mcp-runtime.md)。

新增 MCP 批处理、后端/job 状态和分页接口，使用与限制见 [mcp-runtime-tools.md](mcp-runtime-tools.md)。其余工具迁移、持久恢复、取消、
安装卸载矩阵与完整双后端性能基准仍待完成。
本轮是最小闭环验收，不发 v0.2，不切默认 COM，不声称 HTTP 性能胜出。
