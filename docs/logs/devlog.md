# 开发日志

> 追加式记录，按日期分节。每次对项目做出实质性修改后在这里加一条。

## 2026-07-10

- 分析参考项目 [daobataotie/CAD-MCP](https://github.com/daobataotie/CAD-MCP) 的架构与局限性，落盘到 [docs/references/cad-mcp-analysis.md](../references/cad-mcp-analysis.md)。
- 产出架构设计方案，见 [docs/design/architecture.md](../design/architecture.md)：三层架构（server / tools / cad），确定不自建 NLP 解析层，确定 ProgID 走配置。
- 确认本机环境：AutoCAD 2026 已安装，COM ProgID 为 `AutoCAD.Application.25.1`（注册表确认，通用 ProgID 未注册）。
- 搭建项目骨架：
  - 新建 conda 环境 `autocad-mcp`（Python 3.11），安装 `pywin32` / `mcp[cli]`（1.28.1）/ `pydantic`（2.13.4）/ `pytest`。
  - 建立目录结构：`src/autocad_mcp/{cad,tools}`、`docs/{design,references,logs}`、`tests/`。
  - 完整实现 `cad/connection.py`（COM 连接，支持 ProgID 回退）、`cad/geometry.py`（坐标转 VARIANT）。
  - `cad/controller.py` 只完整实现 `draw_line`，其余（`draw_circle`/`draw_arc`/`draw_polyline`/`draw_rectangle`/`draw_text`/`draw_hatch`/`add_dimension`/`save_drawing`）留 `NotImplementedError` 占位。
  - `cad/query.py` 全部留白（`list_layers`/`query_entities`/`get_entity`/`delete_entity`），是相对参考项目的创新点，下一阶段实现。
  - `tools/` 下按 drawing/query/document 三个模块注册 MCP 工具，`server.py` 汇总注册。
  - `tests/test_connection.py`：需要真实 AutoCAD 运行的手动集成测试。
  - 初始化本地 git 仓库。

**下一步 TODO**：
1. 实现 `draw_circle`/`draw_arc`/`draw_rectangle`/`draw_polyline`/`draw_text`/`draw_hatch`/`add_dimension`/`save_drawing`。
2. 实现 `cad/query.py`（图层列表、实体查询、按 ObjectID 取实体、删除实体）。
3. ~~用 MCP Inspector（`mcp dev`）跑通全部工具列表，实际连 AutoCAD 2026 验证 `draw_line`~~ 已完成，见下方验证记录。

**端到端验证记录**：
- `server.py` 导入正常，8 个 MCP 工具全部注册成功（`draw_line`/`draw_circle`/`draw_arc`/`draw_rectangle`/`draw_text`/`list_layers`/`query_entities`/`save_drawing`）。
- 用真实运行中的 AutoCAD 2026 验证 `connection.py` + `controller.draw_line`：连接成功，`AddLine` 调用成功返回 ObjectID。
- **踩坑**：验证时连接到的是用户当前正在编辑的真实工程图纸（非空白测试文件），测试线段画在了这份真实图纸上；已立即用 `document.SendCommand("_.undo\n1\n")` 撤销。已在 CLAUDE.md 补充安全注意事项：写操作类验证脚本必须先确认 `document.Name`，避免污染用户的真实工作文件。
- `conda run -n autocad-mcp ...` 在 Windows 控制台下遇到中文输出会报 `UnicodeEncodeError`（GBK 编码问题），改用 env 内 `python.exe` 直接调用绕过。

**GitHub 仓库 & 项目管理**：
- 推送到 https://github.com/codesknight/AutoCAD-MCP（分支 `main`）。
- 安装 GitHub CLI（`gh`，winget）并完成账号授权（`codesknight`）。
- 加 `LICENSE`（MIT，与参考项目一致）、`.github/ISSUE_TEMPLATE/`（bug/feature）、`.github/pull_request_template.md`。
- 仓库 topics：`mcp`/`autocad`/`model-context-protocol`/`cad`/`python`/`ai-agents`/`com-automation`。
- 自定义 label：`drawing-tool`、`query-tool`；创建 milestone「MVP: 全部绘图与查询工具落地」。
- 把本节"下一步 TODO"转成 9 个 GitHub Issue（#1–#9：draw_circle/draw_arc/draw_rectangle/draw_text/draw_polyline/draw_hatch/add_dimension/save_drawing/实体查询能力），全部挂到 MVP milestone。
- `main` 分支加保护：禁止 force push、禁止删除分支（个人开发场景，未启用强制 PR review）。
- **踩坑**：`git add -A` 时误把 Claude Code 自身的会话锁文件 `.claude/scheduled_tasks.lock` 提交并推送上去了；已 `git rm --cached` 清除并加入 `.gitignore`。以后 `git add` 前要注意别把 `.claude/` 这类工具内部状态目录带进去。
- Project Board：补上 `project` scope 后建成 [AutoCAD-MCP 开发看板](https://github.com/users/codesknight/projects/2)，9 个 Issue 全部加入，用默认 Status 字段（Todo/In Progress/Done）分列。

## 2026-07-10（续）：实现 draw_circle + 修复零文档连接 bug

- 实现 `cad/controller.py` 的 `draw_circle`（`model_space.AddCircle`），`tools/drawing_tools.py` 接上真实调用，关闭 [#1](https://github.com/codesknight/AutoCAD-MCP/issues/1)。
- **修 bug**：`connection.py` 的 `connect()` 之前假设 AutoCAD 里一定有活动文档，调用 `_wait_for_document()` 死等 15 秒后超时报错。实际测试时 AutoCAD 处于 `Documents.Count == 0`（无文档打开）状态，`ActiveDocument` 直接抛 COM 异常，导致连接失败。修复：`connect()` 里先判断 `Documents.Count`，为 0 就直接调用新增的 `new_document()` 创建一个空白文档，不再死等一个不存在的活动文档。
- 新增 `CADConnection.new_document(template=None)`：调用 `Documents.Add()` 创建全新空白图纸并切换过去，`draw_*` 操作可以在这个新文档上做，不会碰到用户当前正在编辑的真实图纸（呼应此前"踩坑"里定的安全规则）。
- 端到端验证：连接后自动新建 `Drawing1.dwg`，再调用 `new_document()` 切到 `Drawing2.dwg`，在其上 `draw_line` + `draw_circle` 均成功返回 ObjectID。

## 2026-07-10（续二）：按开发看板补完全部工具（#2–#9）

对照 [Project Board](https://github.com/users/codesknight/projects/2) 把剩余 8 个 Issue 全部实现并端到端验证：

- `draw_arc`：`model_space.AddArc`，`start_angle`/`end_angle` 对外接口用「度」，内部转弧度。
- `draw_polyline`：`model_space.AddPolyline`（3D 点拉平成 double 数组），拆出私有 `_add_polyline()` 给 `draw_rectangle`/`draw_hatch` 复用。
- `draw_rectangle`：复用 `_add_polyline`，用对角两点算出四个顶点画闭合多段线。
- `draw_text`：`model_space.AddText`，支持 `rotation`（度）。
- `draw_hatch`：先用 `_add_polyline` 画闭合边界，再 `AddHatch(1, pattern_name, True)` + `AppendOuterLoop` + `Evaluate()`。
- `add_dimension`：`model_space.AddDimAligned`。
- `save_drawing`：`document.SaveAs(file_path)`。
- `cad/query.py`：`list_layers`/`query_entities`/`get_entity`/`delete_entity` 全部实现（O(n) 遍历 ModelSpace，附带类型相关字段：线的起止点、圆/弧的圆心半径、文字内容等）。
- `tools/` 三个模块补齐对应 MCP 工具注册；`query_tools.py` 新增 `get_entity`/`delete_entity` 工具（之前设计里漏注册了）；返回值统一走 `json.dumps`。

**踩坑（3 个，均已修复）**：
1. `hatch.AppendOuterLoop([boundary])` 直接传 Python list 报「参数个数无效」——AutoCAD COM 要求显式的 `VT_ARRAY | VT_DISPATCH` 对象数组，新增 `geometry.to_variant_object_array()` 解决。
2. `Documents.Add()` 的**返回值本身**在 pywin32 动态绑定下不可靠（属性访问会报 `AttributeError: Add.ModelSpace`，即便文档其实已经创建成功并被激活）——`new_document()` 改成不信任返回值，转而通过 `ActiveDocument` 重新取引用。
3. 就算改成走 `ActiveDocument`，新文档的 COM 对象也不是"创建完立刻能用"，第一次访问偶发 `AttributeError: <unknown>.ModelSpace`——是时序问题，`_wait_for_document()` 增加 `AttributeError` 到重试的异常类型里，`new_document()` 复用这个重试逻辑而不是只查一次。
4. 额外一个：`CADQuery` 里如果一直复用 `connection.model_space` 这个缓存的 COM 包装对象反复 `for` 遍历（尤其是删除实体之后），pywin32 会因为内部枚举器（`_enum_`）失效抛 `com_error: 未指定的错误`——改成每次查询都用 `connection.document.ModelSpace` 现取一个新引用，不复用旧的。

**端到端验证**：新建空白图纸，13 个 MCP 工具全部跑了一遍（8 个绘图 + 4 个查询 + save_drawing），`query_entities`/`get_entity`/`delete_entity` 在增删之后重复调用也验证正常。

**尚未做（后续可选优化，不在当前 Issue 范围内）**：`query.py` 目前是线性遍历 ModelSpace，图纸实体数量很大时性能会下降；`save_drawing` 没有校验文件格式/扩展名。

MVP milestone 的 9 个 Issue 已全部关闭（部分靠 commit `closes #N` 自动关，`#3`–`#9` 因为一条 commit message 里只有第一个 `#` 前有 `closes` 关键字生效，手动 `gh issue close` 补关），milestone 已 close。

## 2026-07-10（续三）：开新 milestone，规划 Phase 2

MVP 跑通后，把下一阶段要做的事拆成 4 个新 Issue，开了新 milestone 「Phase 2: 测试、性能与集成验证」（#2），都已加入 Project Board：

- [#10](https://github.com/codesknight/AutoCAD-MCP/issues/10) 补充 pytest 自动化测试覆盖（纯函数单测 + AutoCAD 集成测试）
- [#11](https://github.com/codesknight/AutoCAD-MCP/issues/11) `cad/query.py` 大图纸场景性能优化（当前 O(n) 遍历）
- [#12](https://github.com/codesknight/AutoCAD-MCP/issues/12) 接入 Claude Desktop，做自然语言端到端验证（目前都是直接调 Python 函数测的，还没走过真实 MCP 客户端）
- [#13](https://github.com/codesknight/AutoCAD-MCP/issues/13) `save_drawing` 校验目标路径，避免误覆盖用户真实文件

新增 label：`testing`、`performance`。
