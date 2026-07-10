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
- Project Board（看板）待补：`gh auth` 默认 scope 没有 `project`，已 `gh auth refresh -s project` 走第二次设备授权，等待用户完成后再建。
