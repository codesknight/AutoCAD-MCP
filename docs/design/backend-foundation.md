# COM 后端迁移基础：设计与实施状态

日期：2026-11-18。基线：`5e8379835c7dced142e6fcf9339741975b8dfae0`。

本文记录本轮实际实现；[完整 roadmap](development-roadmap.md) 保留为设计草案，不能视为完成清单。

## 设计选择

先固定 MCP 工具契约，再改内部执行入口。保留 controller/query 原有算法和文件位置，避免迁移算法、线程和工具接口同时变化。`state.py` 只持有一个懒加载 backend，兼容访问器返回操作 facade。查询先于绘图、绘图先于查询、新建图纸先于两者均复用同一 backend/session。

`CadBackend.execute(operation, payload)` 是内部接口；操作来自固定白名单，不注册为通用 MCP 工具。facade 根据既有 Python 方法签名绑定位置参数和关键字参数；输入和结果只允许复制普通数据。参考图纸分析也通过 backend 执行，工具层不再取得 `.connection`。

COM backend 首次执行操作时才启动独立 STA 线程。在同一线程初始化 COM、创建 connection/controller/query、串行执行、泵送消息及释放引用。最多排队 64 项，满队列明确报错。关闭时停止接收请求、排空已接收任务、在所属线程释放引用并反初始化 COM；不保存、关闭图纸或退出 CAD。原生调用执行期间不能承诺立即中断，关闭会等待其返回。工作线程异常退出会使等待请求失败，不留下永远等待的 Future。

配置缺省 `backend="com"`，旧 JSON 配置仍有效。`backend="http"` 暂时明确返回 `UNSUPPORTED_BACKEND`，不隐式回退。HTTP adapter、Bridge DTO、实例状态、认证和事务协议要等插件最小闭环验证后实现，避免提供无法兑现语义的空壳。

## 文档与恢复边界

- 新建图纸刷新共享 connection 的 document/model_space；两项引用仅在均读取成功后一起替换。
- 执行前比较绑定文档与当前活动文档的名称；切换后拒绝操作。通过 `new_drawing` 创建新 scratch，或显式关闭/重建后端以重新选择活动文档。原生调用失败后不自动重放。
- 参考分析结束后核对原文档名称；旧 helper 恢复失败时清空文档引用，阻止后续写入被隐式重定向。
- 名称检查是旧 COM 的保守防护，**不是**稳定文档会话 ID，也不能保证用户在执行中切图时的强一致性。Bridge 仍需实现 instance_id/document_id、提交时绑定、权限和 revision。
- 串行队列覆盖一个 MCP 服务进程。多个独立 MCP 进程仍没有跨进程单写协调，不能据此声称多进程写入安全；COM 运行时应只使用一个写入口。
- FastMCP HTTP 的低层生命周期按客户端会话运行：计数共享会话，仅最后一个会话退出时关闭 backend；清理使用 AnyIO cancellation shield，防止断连取消跳过释放。

## 本轮验证

1. 重构前固定 36 个工具的名称、描述、输入和输出 schema：`tests/fixtures/mcp-tools-v0.1.json`。随后用实际 stdio `initialize` / `tools/list` 与快照比较。
2. 32 个 CAD 工具的参数映射、默认值与原有字符串/JSON 返回经真实内存 MCP JSON-RPC 测试，使用 fake CAD；样例为合成值，不是实机结果。其余 4 个本地资源/VQA 工具只冻结 schema。
3. 离线回归覆盖访问顺序、单例、线程归属、并发串行、队列上限、关闭、显式重连、失败连接、写操作不重放、工作线程故障、文档切换、参考恢复失败和多个 MCP 会话。
4. `python -m pytest -q`：56 passed、33 skipped。实机测试必须显式 `--cad-integration`；默认测试不会为了集成测试启动 CAD。
5. `python -m pytest tests/test_backend_integration.py --cad-integration -q -s`：2 passed。实际 AutoCAD 新建专用空白图纸，验证 STA adapter 的线/圆/图层创建与重读、显式重连，以及真正 stdio MCP 客户端的发现、创建和坐标重读。

重构前曾运行 8 项既有测试，其中包括会自动启动 CAD 的集成测试：8 passed，但输出含 COM 忙碌异常诊断。这不是稳定性证明，也不是性能基准。本轮新增测试仅是小规模 smoke，不代表旧工具全部通过实机回归。环境记录见 [baseline-2026-11-18.json](baseline-2026-11-18.json)。

## Roadmap 对照与下一步

| 任务 | 当前状态 | 尚需验证/实施 |
| --- | --- | --- |
| CAD-01 基线与契约 | 部分完成：SHA、环境、schema、合成调用 fixture | COM 原始性能样本、公平 fixture、完整集成回归 |
| CAD-02 生命周期 | 基础完成；离线和小规模实机通过 | CAD 重启/关闭图纸/忙碌状态的系统故障测试 |
| CAD-03 backend/factory | COM adapter 与 STA 基础完成 | 类型化 Bridge DTO、状态/能力的公开协议、双后端契约 |
| CAD-04 原生插件 | 未实施；检测到本机 .NET SDK 缺失 | 确认 AutoCAD 更新版本与官方运行时兼容表、SDK、NETLOAD |
| CAD-05 至 CAD-09 | 未实施 | Bridge 认证/调度/文档会话、首批操作、原子批处理、HTTP adapter、实测 Benchmark |

下一轮先完成 CAD-04 的版本/SDK Spike 和最小 NETLOAD 插件，再开发认证的 loopback health/status 与安全 Dispatcher。原子性、去重、HTTP 性能和默认后端切换均没有通过验收；本轮不改默认 COM，也不发布 v0.2。

## 开发命令

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
python scripts/export_mcp_contract.py --output tools.json
# 先启动 AutoCAD；会创建专用测试图纸：
python -m pytest tests/test_backend_integration.py --cad-integration -q -s
```

CI 使用 Windows runner 安装 pywin32，运行默认离线套件，不使用 CAD 许可证、私有 DWG 或模型凭证。
