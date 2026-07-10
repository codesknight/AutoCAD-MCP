# 项目约定

毕设项目：AutoCAD MCP 服务，参考并改进自 [daobataotie/CAD-MCP](https://github.com/daobataotie/CAD-MCP)（分析见 [docs/references/cad-mcp-analysis.md](docs/references/cad-mcp-analysis.md)，架构方案见 [docs/design/architecture.md](docs/design/architecture.md)）。

## 日志规则（重要，必须遵守）

**每次对本项目做出实质性修改**（新增/修改功能、调整架构、修复 bug、更新依赖等）之后，必须在 [docs/logs/devlog.md](docs/logs/devlog.md) 追加一条记录：
- 找到今天日期对应的 `## YYYY-MM-DD` 分节，没有就新建一个（日期用当天真实日期，不要用相对时间）。
- 用简短要点写清楚"改了什么、为什么改"，而不是逐行代码变更。
- 不要覆盖或删除历史条目，只追加。

## 架构原则

- 三层结构：`server.py`（MCP 入口）→ `tools/`（MCP 工具，参数校验）→ `cad/`（COM 自动化，不依赖 mcp 包）。新增能力时严格按这个分层放代码，不要在 `tools/` 里直接写 COM 调用。
- **不要自己写自然语言解析层**（不要重蹈参考项目 `nlp_processor.py` 的覆辙）。MCP 客户端本身负责自然语言理解，工具函数只接收结构化参数。
- AutoCAD COM ProgID 从 `src/autocad_mcp/config.json` 读取（当前为 `AutoCAD.Application.25.1`），不要硬编码 `"AutoCAD.Application"`——本机注册表里这个通用 ProgID 并未注册。
- 坐标传给 COM 方法前必须用 `cad/geometry.py` 里的 `to_variant_point` 转成 VARIANT 数组。

## 环境

- conda 环境名：`autocad-mcp`（Python 3.11）。命令行直接调用建议用 `"/c/Users/LiuYanhong/.conda/envs/autocad-mcp/python.exe" script.py`（Windows 上 `conda run` 在遇到中文/非 ASCII 输出时会因为控制台 GBK 编码而报 `UnicodeEncodeError`，用 env 内的 python.exe 直连可绕开）。
- 集成测试（`tests/test_connection.py` 等）需要真实打开的 AutoCAD 实例，连不上时应 `pytest.skip` 而不是报错失败。

## ⚠️ 安全注意事项

用户的 AutoCAD 里经常开着**真实的工程图纸**（不是空白测试文件）。`GetActiveObject` 连接的是当前活动实例的**当前活动文档**——任何写操作（画线、保存等）都会直接作用在用户正在编辑的真实图纸上。

- 写操作类的手动验证脚本，跑之前先打印 `conn.document.Name` 确认（或者要求用户新建一个空白图纸再测试），不要默认往当前活动文档里写测试数据。
- 如果不小心在真实图纸上执行了测试性质的绘制，立刻用 `document.SendCommand("_.undo\n1\n")` 撤销，并明确告知用户改了什么、已撤销。
- 涉及 `save_drawing`（另存为/覆盖保存）等不可逆操作时，默认写到新文件路径，不要覆盖用户原文件，除非用户明确要求。
