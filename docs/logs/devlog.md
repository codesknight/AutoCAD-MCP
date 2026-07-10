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

## 2026-07-10（续四）：[#12] 接入 Claude Desktop（配置 + 协议级验证已完成，等用户做自然语言实测）

- 发现本机安装的桌面客户端配置文件在 `%APPDATA%\Claude\claude_desktop_config.json`，是一个统一了经典 Claude 对话 + Cowork/Claude Code 的新版客户端（原文件里已经有 `coworkUserFilesPath`/`preferences` 等键，没有 `mcpServers`）。编辑前先备份了一份（`claude_desktop_config.json.bak-<时间戳>`），然后新增 `mcpServers.autocad-mcp` 这个顶层键，其余原有内容原样保留。
- `command` 直接指向 `C:\Users\LiuYanhong\.conda\envs\autocad-mcp\python.exe`，`args: ["-m", "autocad_mcp.server"]`——不用 `conda run`，避免客户端拉起子进程时环境变量不全 / Windows 控制台编码的问题（README 里的示例也同步改了）。
- **协议级验证**：没有直接调用 Python 函数走捷径，而是用 `mcp` 官方客户端 SDK（`mcp.client.stdio.stdio_client` + `ClientSession`）按配置里完全一致的命令拉起 `server.py` 子进程，走真正的 MCP stdio 协议 `list_tools`/`call_tool`：13 个工具全部可见，`draw_circle` 调用成功。验证脚本里按 CLAUDE.md 的安全规则，先检查了 `ActiveDocument` 确实是我们自己建的无路径 `Drawing7.dwg` 空白测试文件，才允许继续执行写操作（Claude Code 的 auto-mode 权限分类器一开始就因为脚本没做这个检查直接拦截了，加上检查后才放行——说明这条安全规则已经在生效）。
- **还没做（需要用户在真实客户端里操作，我没法代劳）**：重启客户端让配置生效，然后在新对话里用自然语言实际触发这 13 个工具，看看哪些工具的参数描述/命名对 AI 不够清晰（比如角度单位、暂时没做的颜色参数），以及真实报错信息是否对用户友好。Issue #12 先不关，等用户反馈。

## 2026-07-10（续五）：新增网页 UI + 多大模型接入（保留 MCP 协议）

用户想换一种交互方式：自己做网页界面，自己填大模型 API Key（Claude / OpenAI / 国产 OpenAI 兼容模型都要支持且可切换），但明确要求**保留 MCP 协议**——网页后端要当一个自建的 MCP client 连接现有 `server.py`，不能绕开 MCP 直接把 `cad/` 函数包成 tool schema。

**新增内容**：
- `src/autocad_mcp/server.py`：加了 `--http` 启动方式（`mcp.run(transport="streamable-http")`，端口 8931），默认 stdio 行为不变，Claude Desktop 配置不受影响，两条集成路径共存。
- `web/backend/mcp_client.py`：真正的 MCP client（`mcp.client.streamable_http`），连 `http://127.0.0.1:8931/mcp`，不是直接 import `autocad_mcp.cad`/`tools`。
- `web/backend/providers/`：多模型适配层。`base.py` 定义统一接口；`anthropic_provider.py`（官方 `anthropic` SDK，模型 `claude-opus-4-8`，MCP 的 `Tool.inputSchema` 几乎直接就是 Anthropic 的 `input_schema`）；`openai_provider.py`（官方 `openai` SDK，`base_url` 可传，同时覆盖真 OpenAI 和国产 OpenAI 兼容模型如通义千问/DeepSeek/智谱）。
- `web/backend/agent_loop.py`：手写 agentic loop（不用 SDK 自带的 tool_runner，因为工具执行要走 `mcp_client` 而不是本地函数），上限 8 轮工具调用防止死循环。
- `web/backend/conversation_store.py`：进程内内存存会话历史，不落盘（已知限制，写进 README）。
- `web/backend/app.py`：FastAPI，`POST /api/chat`，API Key 只在单次请求里用，不记日志不落盘；挂载 `web/frontend/` 静态文件。
- `web/frontend/`：纯静态 `index.html` + `app.js`（无构建步骤），模型下拉框 + API Key 输入框（`type=password`，只存浏览器内存）+ base_url 输入框（选 OpenAI 兼容时才显示）+ 聊天记录。
- `pyproject.toml` 加 `[project.optional-dependencies] web`（`anthropic`/`openai`/`fastapi`/`uvicorn[standard]`），装进已有的 `autocad-mcp` 环境。

**端到端验证**（没有真实大模型 API Key，只测了不需要 key 的部分 + 用假 key 验证到认证边界为止）：
- `mcp_client.py` 通过真实 streamable-http 协议连上 `server.py --http`：13 个工具全部可见，`draw_line` 调用成功画出线（验证脚本按 CLAUDE.md 规则先确认了活动文档是自己建的空白 `Drawing7.dwg`）。
- FastAPI 后端起来后，用浏览器（preview 工具）填假 API Key 发消息，请求链路走到了 `agent_loop → mcp_client.list_tools() → AnthropicProvider.chat() → 真实 Anthropic API`，拿到了预期的 `401 invalid x-api-key` 认证错误——证明整条链路在真正调用外部大模型这一步之前全部正确，只是没有真 key 没法测完整的 tool-calling 循环。
- 顺手把 `/api/chat` 的异常处理改成把大模型调用失败包成正常聊天回复（`出错了：...`），而不是裸 500，验证过修复后表现正常。

**尚未验证（需要用户拿真实 API Key 自己测）**：完整的 tool-calling 循环（大模型真的读懂工具描述、生成正确参数、`agent_loop` 正确执行并把结果喂回去、最终产出合理的文字回复）；OpenAI/国产 OpenAI 兼容模型那条分支目前只做了代码走查，没有实际调用测试过。

开了新 milestone「Phase 3: 网页 UI 完整验证与增强」（#3），补了 3 个 Issue 到看板：[#14](https://github.com/codesknight/AutoCAD-MCP/issues/14) 用真实 API Key 完整验证 Claude tool-calling 循环、[#15](https://github.com/codesknight/AutoCAD-MCP/issues/15) 验证 OpenAI/OpenAI 兼容模型分支、[#16](https://github.com/codesknight/AutoCAD-MCP/issues/16) 网页聊天支持流式响应。

（顺手踩了个小坑：复制命令时手滑多建了一个叫「temp」的空 Project 看板，发现后立刻 `gh project delete` 删掉了，不影响正式看板 #2。）

## 2026-07-10（续六）：修 bug——OpenAI 兼容模式模型名写死

用户实测时选了 DeepSeek 的 OpenAI 兼容接口，画一个圆圈报错：`The supported API model names are deepseek-v4-pro or deepseek-v4-flash, but you passed gpt-4o.`——原因是 `openai_provider.py` 里 `DEFAULT_MODEL` 写死成了 `"gpt-4o"`，没给用户填模型名的地方。

- 网页前端加了「模型名称」输入框，`openai_compatible` 模式下前端+后端双重校验必填（不同厂商模型名完全不一样，没法给合理默认值）。
- `ChatRequest`/`run_turn`/`AnthropicProvider`/`OpenAIProvider` 都加了可选 `model` 参数，一路透传下去；Anthropic 模式留空时仍用默认的 `claude-opus-4-8`。
- 用假的 `https://api.deepseek.example.com/v1` + `deepseek-v4-pro` 在浏览器里实测：请求确实带着指定的 base_url 和 model 送出去了（`mcp_client.list_tools()` 先正常跑通，说明 MCP 那一段没受影响），只是因为域名是假的最后报了 DNS 连接错误——证明这次的 fix 生效了，模型名传递链路没问题。前端"必填校验"也验证过：不填模型名点发送，请求根本不会发出去。

**用户用真实 DeepSeek API Key 验证成功**：接入 DeepSeek（OpenAI 兼容模式）跑通了完整的 tool-calling 循环。至此 [#15](https://github.com/codesknight/AutoCAD-MCP/issues/15) 的 OpenAI 兼容分支部分已验证；真 OpenAI（`gpt-4o` 等）还没有实测过，issue 先不关。

## 2026-07-10（续七）：网页 UI 支持上传图片让模型参考着画图

用户想要"上传一张图片，让模型照着画"。做法：不用额外写图像处理管道，直接把图片作为多模态输入的一部分传给大模型（vision），模型看完图之后照样用已有的 `draw_*` 工具画——工具调用循环完全复用，只是"用户消息"这一步多了一个图片 content block。

- `providers/base.py`：`LLMProvider` 加抽象方法 `build_user_message(text, image_base64, image_media_type)`。
- `anthropic_provider.py`：图片按 Anthropic 的 `{"type": "image", "source": {"type": "base64", "media_type", "data"}}` 格式拼进 content 数组。
- `openai_provider.py`：图片按 OpenAI 的 `{"type": "image_url", "image_url": {"url": "data:...;base64,..."}}` 格式拼。
- `agent_loop.run_turn`：改成自己负责构造并 append 用户这一轮的消息（而不是像之前那样由 `app.py` 直接拼一个纯字符串），因为要按选中的 provider 决定用哪种图片格式。
- `app.py`：`ChatRequest` 加 `image_base64`/`image_media_type` 两个可选字段。
- 前端：加了文件上传控件，用 `FileReader.readAsDataURL` 转 base64，发送前有缩略图预览，发送后自动清空。没填文字但传了图的话，会用一个默认 prompt（"请根据这张图片，用现有工具在 AutoCAD 里画出对应的图形。"）。

**端到端验证**：因为 preview 工具不支持模拟真实的文件选择对话框，用 `preview_eval` 直接注入了一张 1x1 测试 PNG 的 base64 数据（跳过了 `FileReader` 那段标准浏览器 API，风险很低），走完整的发送流程：请求体正确带上了 `image_base64`/`image_media_type`，后端 `agent_loop → AnthropicProvider.build_user_message` 构造出的多模态消息被 Anthropic API 接受到了认证检查这一步（拿到预期的 401，不是 400 格式错误），说明图片 content block 格式是对的。前端"发送后清空图片"的逻辑也验证正常。

**尚未验证（需要真实 API Key 和真图片）**：模型看图之后能不能画出靠谱的东西（这本身是个近似任务，取决于模型能力，不是代码 bug 范畴）；OpenAI 分支的图片格式没有实测（DeepSeek 的文本模型 `deepseek-v4-pro` 大概率不支持 vision，需要专门的视觉模型）。开了 [#17](https://github.com/codesknight/AutoCAD-MCP/issues/17) 跟进，已加入看板。
