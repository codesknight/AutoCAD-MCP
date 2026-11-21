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

## 2026-07-11：修 DeepSeek/智谱 base_url 报错 + 新增豆包原生 SDK 接入

**先纠正一个问题**：上一次跟用户说"DeepSeek/智谱的 base_url 修复已提交推送"，实际上当时只改了代码没有真的 `git commit`——这次一起补提交了（1a67265），以后每次改完代码要记得实际跑 `git commit`/`push`，不能只是说了但没做。

**用户反馈的两个真实报错**：
1. DeepSeek：`unknown variant \`image_url\`, expected \`text\`` —— DeepSeek 的 `deepseek-v4-pro`/`deepseek-v4-flash` 这类模型压根没有 vision 能力，消息格式里不认 `image_url`，不是我们代码的问题。
2. 智谱：`404 .../v4/chat/completions/chat/completions` —— 用户把 Base URL 填成了带 `/chat/completions` 的完整端点，而 OpenAI SDK 会自动在 base_url 后面拼 `/chat/completions`，导致路径重复。正确的智谱 Base URL 应该是 `https://open.bigmodel.cn/api/paas/v4/`（[官方文档](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction)）。

**修复**：
- `openai_provider.py` 加 `_normalize_base_url()`，自动去掉用户误填的末尾 `/chat/completions`，防止路径重复。
- `app.py` 遇到"模型不支持图片输入"这类报错时，先给一句人话提示，再附原始报错。
- 前端 Base URL 输入框下面加了正确示例提示（通义千问/DeepSeek/智谱各自的根路径）。

**新增：豆包（Doubao）原生 SDK 接入**：用户明确要的是接火山引擎的原生 Ark SDK（而不是复用现有的"OpenAI 兼容"选项，虽然理论上后者也能用，因为豆包/火山方舟本身就是 OpenAI 协议兼容的）。

- 装了 `volcengine-python-sdk[ark]`（模块名 `volcenginesdkarkruntime`），查了 SDK 源码确认 `Ark`/`AsyncArk` 客户端的 `chat.completions.create()` 请求/响应结构跟 OpenAI SDK 完全同构（`ChatCompletionMessage`/`tool_calls`/`image_url` content part 字段都一样）。
- `doubao_provider.py`：`DoubaoProvider` 直接继承 `OpenAIProvider`，只重写 `_build_client()`（用 `AsyncArk` 换掉 `openai.AsyncOpenAI`，默认 base_url `https://ark.cn-beijing.volces.com/api/v3`），工具调用解析/`format_tool_result`/`build_user_message` 全部复用，没有重复代码。
- `agent_loop.py`：加了 `MODEL_REQUIRED_PROVIDERS = ("openai_compatible", "doubao")`，豆包模式下模型名（火山方舟的推理接入点 ID，如 `ep-xxxxxxxx-xxxxx`）必填，没有默认值。
- 前端加了"豆包 (Doubao / 火山方舟 Ark)"选项，复用 Base URL 提示行（留空会用默认值）。

**端到端验证**：起真实 MCP HTTP server + 网页后端，选豆包、填假 API Key + 假 endpoint ID 发消息：请求先正常走完 `mcp_client.list_tools()`，然后真的打到了火山方舟的 Ark API，拿到服务端返回的 `401 AuthenticationError: API key format is incorrect`——证明整条链路（MCP 工具列表 → DoubaoProvider → AsyncArk → 真实 Ark 服务端）是通的，只是假 key 格式不对。

## 2026-07-11（续）：新增 `ask_drawing_vqa` 工具，接入另一个毕设项目（电力工程图纸 VQA 微调模型）

把另一个毕设项目（`D:\LiuYanhong\Projects\BISHE\data`，InternVL3-8B + LoRA 微调的 110kV 变电站图纸理解模型，LLM-judge 29.24%）接进来，作为 MCP 工具暴露给 AI 客户端调用。

**架构决策：模型不进本项目进程，走独立 HTTP 服务**：
- 模型依赖（torch/transformers/peft/bitsandbytes）体积大，和本项目环境（`pywin32` + `mcp[cli]`）没有交集，混进来会让两边依赖互相拖累。
- 本机只有 8GB 显存，模型要 4bit 量化才能装下，加载耗时 ~20s，单题推理 90~130s——每次工具调用都重新加载模型不现实，必须常驻单独进程。
- 于是新增 `D:\LiuYanhong\Projects\BISHE\data\Models\vqa_api_server.py`（FastAPI，跑在 `power_vqa` conda 环境，监听 `127.0.0.1:8933`），模型只加载一次；本项目这边只加一个薄薄的 HTTP client 转发层，符合本项目自己的分层约定（`tools/` 层只做参数校验+转发）。

**改动**：
- 新增 `src/autocad_mcp/tools/vqa_tools.py`：`ask_drawing_vqa(image_path, question)` 转发到本地 VQA API；`vqa_service_status()` 查服务是否就绪；服务没起来时给出人话提示（附带启动命令），不是裸抛连接异常。
- `server.py` 注册新工具；`pyproject.toml` 核心依赖加 `httpx`（其实 `mcp[cli]` 已经传递依赖了 `httpx`，但既然本项目直接 import 用它，显式声明更清楚）。

**踩坑**：`vqa_api_server.py` 顶部文档字符串里直接写了 Windows 路径（`"C:\Users\...`），触发了 `\U` 被当成 8 位十六进制 Unicode 转义符导致 `SyntaxError: (unicode error) 'unicodeescape' codec can't decode bytes`——docstring 里带反斜杠路径必须用 `r"""..."""` 或把反斜杠转义成 `\\`。

**端到端验证**：先起 `vqa_api_server.py`（4bit量化加载模型，显存占用5.68GB），`curl /health` 确认就绪；再直接调用 `ask_drawing_vqa` 工具函数（不经过完整 MCP 协议，直接从 `server.mcp._tool_manager._tools` 里取出函数调用，等价于验证核心逻辑）：传入本地一张评估集图纸 + "图中标注了几台主变压器？"，正确返回"1台"；换一张图问母线配置，正确返回"该变电站采用单母线分段接线，共设置两段母线，分别为I段和II段"。两次请求耗时都在 90~120s 区间，符合本机硬件预期。

**使用方式**：这两个服务都要手动起，都是长期驻留进程：
```bash
# 1. 先起VQA API服务（power_vqa环境）
cd D:\LiuYanhong\Projects\BISHE\data\Models
"C:\Users\LiuYanhong\.conda\envs\power_vqa\python.exe" -m uvicorn vqa_api_server:app --host 127.0.0.1 --port 8933

# 2. 再起MCP server（autocad-mcp环境，跟以前一样）
```

**尚未验证**：没有走完整 MCP 协议（stdio/streamable-http）从 Claude Desktop 或网页 UI 里实际调用这个新工具，只验证了工具函数本身的逻辑。也没有做"先截图/导出当前 AutoCAD 图纸再喂给 VQA 模型"这一步——目前 `image_path` 需要调用方（AI客户端）自己提供一张已存在的图片路径，本项目暂时没有"导出当前视图为PNG"的工具，如果要打通"直接问当前打开的AutoCAD图纸"这个体验，还需要补一个截图/导出工具。

**补充验证（2026-07-11）**：用真实 MCP 协议（`web/backend/mcp_client.py` 的 streamable-http client，跟网页 UI 走的是同一条路径）调用 `ask_drawing_vqa`，`vqa_api_server.py` 真实跑着（`power_vqa` 环境，InternVL3-8B + LoRA），传入评估集图片 `test_001.png` + "图中标注了几台主变压器？"，模型真实回答"2台，分别为1号主变和2号主变"。`list_tools()` 显示 15 个工具（13 个原有 + `ask_drawing_vqa`/`vqa_service_status`）。**结论：`vqa_tools.py` 注册进 `server.py` 之后，天然就是网页 UI（或 Claude Desktop）里任意一个"大脑"LLM 都能调用的工具，不需要为这个本地模型单独写接入代码**——这就是分层 MCP 架构的意义：新工具只要注册进 `server.py`，所有 MCP client 自动可见。真正缺的还是"先截图/导出当前 AutoCAD 视图"这一步，`image_path` 目前得指向一张已经存在的图片文件。

## 2026-07-11（续二）：网页 UI 支持本地自己部署的模型服务

用户想让网页 UI 能接自己写的本地模型 API 服务（类似 `vqa_api_server.py` 那种自建服务，走 OpenAI 兼容协议但不做真实鉴权）。现有的"OpenAI 兼容"选项理论上已经支持任意 base_url，唯一的障碍是前端强制要求填 API Key。

- 前端去掉了"未填 API Key 就 alert 拦截"的校验，改成允许留空。
- `app.py` 的 `ChatRequest.api_key` 默认值改成 `""`（本来就是 `str` 类型，Pydantic 没拦，只是前端拦了）。
- `openai_provider.py` 的 `_build_client()`：如果 `api_key` 是空字符串，用占位符 `"not-needed"` 兜底——因为 `openai` SDK 在构造 client 时如果 `api_key` 为空/None 会直接报错（`Missing credentials`），不管目标服务器实际要不要鉴权都得先满足 SDK 自己的这道检查。
- 前端 Base URL 提示行加了一句：本地自己部署的服务（如 `http://127.0.0.1:8000/v1`）也可以直接填，通常不需要真实 API Key。

**端到端验证**：起真实 MCP HTTP server + 网页后端，选"OpenAI 兼容"、Base URL 填一个没有服务监听的假本地地址（`http://127.0.0.1:9999/v1`）、**API Key 留空**发消息：请求没有被前端拦截，正常发出，`mcp_client.list_tools()` 正常跑完，最后因为目标端口没有服务而报连接错误（预期行为，证明请求确实是不带真实 key 打过去的，不是在验证阶段就被挡住）。

## 2026-07-11（续三）：新增 `export_current_view`，打通"直接问当前打开的图纸"闭环

补上一直缺的一环：把当前 AutoCAD 视图导出成 PNG，喂给 `ask_drawing_vqa`，不用再手动指定一张已存在的图片路径。

**实现**：`cad/controller.py` 新增 `export_current_view(file_path=None, timeout=30.0)`，用 AutoCAD 自带的 `PublishToWeb PNG.pc3` 光栅打印驱动导出全图。`file_path` 不填会在系统临时目录（`%TEMP%/autocad_mcp_exports/`）自动生成一个。注册为 MCP 工具 `export_current_view`（`tools/document_tools.py`）。

**踩坑（3 个，都是 AutoCAD 打印自动化的经典坑，逐个调试解决的）**：
1. **`PlotToFile` 是异步的**：调用后立刻返回，文件在后台慢慢写，函数返回时文件可能还不存在。第一次测试 `file exists: False`。修复：加 `_wait_for_stable_file()`，轮询等文件出现且大小连续两次不变才算写完，带超时。
2. **换打印驱动后纸张/介质没跟着刷新，打印任务默默失败**：只设 `layout.ConfigName = "PublishToWeb PNG.pc3"` 不够，必须显式调用 `layout.RefreshPlotDeviceInfo()`。一开始还以为要手动指定介质名 `"MaxSize"`，结果报"参数无效"——查了 `layout.GetCanonicalMediaNames()` 才发现这个驱动的介质名是按分辨率命名的（如 `FHD_(1920.00_x_1080.00_Pixels)`），根本没有 `MaxSize` 这个选项；`RefreshPlotDeviceInfo()` 本身就会自动选一个合理默认值（如 `Sun_Hi-Res_(1600.00_x_1280.00_Pixels)`），不用手动指定。
3. **全新图纸的 `layout.ConfigName`/`CanonicalMediaName` 初始是空字符串**：导出完想把配置改回原样，直接把空字符串赋值回去会报"参数无效"（COM 不接受把打印设备设成"无"）。修复：只有原来确实配置过打印设备（非空）才恢复。
4. **导出的图默认转了 90 度**：`RefreshPlotDeviceInfo()` 默认把 `PlotRotation` 设成 1（90°），是 AutoCAD 为了让图纸长宽比更贴合纸张比例做的"最佳适配旋转"，但会导致图纸文字全部躺倒，对 VQA 模型读图不友好。修复：显式设 `layout.PlotRotation = 0`，强制不旋转。

**端到端验证**：用真实 MCP 协议依次调用 `export_current_view`（不传路径，自动生成）→ `ask_drawing_vqa`（把导出的图片路径传进去，问"这张图里有几个图形？"），VQA 模型真实回答"一共有2个图形，一个是圆形，一个是斜线"——跟测试图纸内容（一个圆+一条斜线+文字，文字被合理排除在"图形"之外）完全对得上，肉眼核对导出的 PNG 图片也确认无误（不再是 90 度躺倒的）。至此"用自然语言问当前打开的 AutoCAD 图纸"这个体验完整打通，不需要用户手动导出图片。

## 2026-07-11（续四）：排查"网页调用 ask_drawing_vqa 卡住"

用户反馈网页上试 `ask_drawing_vqa` 时页面卡住不动。直接用真实 MCP 协议复现（`test_002.png`/`test_003.png`/`test_004.png` + 全新问题，排除缓存影响）：4 次调用全部在 2~4.5 秒内成功返回，没能复现"卡住"或超时。说明这次 VQA 服务本身响应很快（跟之前 devlog 记的"单题 90~130 秒"数字对不上——可能那次是冷启动/更复杂的图或问题，具体原因还不确定，模型响应时间本身不是本项目代码能控制的）。

虽然没复现出真正的卡死，但排查过程中确认了两个真实存在、值得先修的问题：

1. **前端完全没有等待反馈**：`app.js` 发送请求后只是把发送按钮禁用，聊天记录框在等响应期间不会有任何变化——哪怕正常等十几秒，观感上也跟"卡住了"没区别。**修复**：加了一个动态更新的"思考中...（已等待 N 秒）"提示，请求结束后移除。
2. **`web/backend/mcp_client.py` 里 `ClientSession.call_tool()` 没有显式传 `read_timeout_seconds`**：如果调用链变慢（尤其是网页场景下"大脑 LLM 决定调用 → 执行 → 大脑读结果生成回复"这一整套流程比单独调工具慢），有可能被某一层的默认超时（比如 streamable-http 传输默认 `sse_read_timeout=300s`，或 session 层未设置时的隐式默认值）提前打断，且当时不会有清晰的报错。**修复**：显式传 `read_timeout_seconds=timedelta(seconds=300)`，给足 VQA 这类慢工具的余量。

两处修复都已验证过不报错、正常工作（用全新的图片+问题重新跑了一遍，2.x 秒内成功）。**用户需要重启网页后端进程**（`uvicorn web.backend.app:app`）才能让这些改动生效——运行中的进程没开热重载。

如果重启后再试还是卡住，需要用户提供更具体的复现信息（选的哪个大脑模型、卡住时浏览器控制台有没有报错、是整个页面都无法操作还是只是聊天没反应）才能进一步排查。

## 2026-07-11（续五）：补图块、变换、图层管理、MTEXT——冲着"复杂图纸"这个目标

用户问"要实现复杂图纸的绘制和理解还缺什么"。分析下来最大的两个缺口：

1. **没有图块能力**：电力工程图纸（变压器/断路器/隔离开关/母线）几乎全靠标准图块符号表达，之前完全没有插入/枚举图块的工具。
2. **没有编辑能力**：之前 8 个绘图工具全是"从零画新实体"，完全没有移动/旋转/复制/缩放/镜像已有实体的能力——真实制图大量是编辑，不是从零画。

这次一口气加了 12 个新工具（现在总共 28 个）：

- `cad/controller.py` 新增：`draw_mtext`（多行富文本，`AddMText`）、`list_blocks`/`insert_block`（`Blocks` 集合枚举 + `ModelSpace.InsertBlock`，`block_name` 可以是图纸里已有的图块名，也可以是一个 .dwg 文件路径——AutoCAD 会自动把外部 dwg 定义成同名图块）、`create_layer`/`set_layer_properties`（`Layers.Add`，颜色/锁定/冻结/可见性）。
- `cad/query.py` 新增：`move_entity`/`rotate_entity`/`copy_entity`/`scale_entity`/`mirror_entity`（全部复用已有的 `_find_entity(object_id)` 按 ID 查找模式，用 AutoCAD 实体自带的 `Move`/`Rotate`/`Copy`/`ScaleEntity`/`Mirror` 方法——`ScaleEntity` 不叫 `Scale` 是因为 `Scale` 在 COM/VBA 里是保留名）、`get_block_attributes`/`set_block_attribute`（图块属性 tag→value）。`_entity_summary()` 顺手扩展：`AcDbBlockReference` 类型会额外报 `block_name`/`insertion_point`/`rotation`/`attributes`，让 `query_entities` 能精确识别图块符号，不用靠 VQA 猜。

**端到端验证**：这次很少见地一次性全部通过，没踩到新的 COM 坑（大概是因为 Move/Rotate/Copy/ScaleEntity/Mirror 这类"标准实体方法"比之前折腾的打印/图块自动定义相关 API 成熟很多）。用 AutoCAD 自带的 `Express/brkline.dwg` 当外部图块测试插入，`list_blocks` 确认自动定义成功；画一条线做移动(5,5,0)→旋转90°→复制偏移(20,0,0)→以端点为基点缩放2倍→镜像，每一步返回的坐标都手算验证过完全正确。之后又用真实 MCP streamable-http 协议重新跑了一遍全部新工具，确认协议层（JSON schema 参数）也没问题。

**尚未做（记入 architecture.md 的"开放问题"，作为下一步 roadmap）**：按区域批量选择/查询（`query_entities` 目前仍是全表扫描）；电力工程标准图块符号库（现在还得自己找 .dwg 文件当图块用）；图块属性批量填报/校核。

**GitHub 项目管理**：开了新 milestone「Phase 4: 复杂图纸支持（图块/变换/图层）」（#4），本次做完的 4 项（[#21](https://github.com/codesknight/AutoCAD-MCP/issues/21) 图块、[#22](https://github.com/codesknight/AutoCAD-MCP/issues/22) 变换、[#23](https://github.com/codesknight/AutoCAD-MCP/issues/23) 图层+MTEXT、[#24](https://github.com/codesknight/AutoCAD-MCP/issues/24) 图块查询扩展）已关闭；剩下的 3 项 roadmap（[#25](https://github.com/codesknight/AutoCAD-MCP/issues/25) 按区域批量选择、[#26](https://github.com/codesknight/AutoCAD-MCP/issues/26) 标准图块符号库、[#27](https://github.com/codesknight/AutoCAD-MCP/issues/27) 图块属性批量填报）开着，都加进了[看板](https://github.com/users/codesknight/projects/2)。

## 2026-07-11（续六）：[#26] 用户提供的真实数据集直接解决了标准图块符号库这个缺口

用户指了两个本地数据集目录：
1. `UnderstandingCircuitDiagrams-VQA/origin-data`——国家电网 110kV 变电站通用设计 PDF+CAD 原始资料（227 个 dwg + 221 个 pdf，按图纸编号如 110-A1-1 组织，含图纸+说明），大概率是之前给 VQA 模型微调用的原始素材，先记录下来，这次没有直接动它。
2. `UnderstandingCircuitDiagrams-206Origin/源数据`——一个巨大的电气 CAD 图纸集合（**38908 个 dwg 文件**），里面有个子文件夹「电力设计一次元件带属性的块集合」，正好是一组独立的标准电力设备符号（断路器/隔离开关/各类变压器/避雷器/电压互感器等 19 个文件，每个文件就是一个符号）。

**验证**：用真实文件测了 `insert_block`——`CIRCUIT BREAKER.dwg`/`DISCONNECTOR.dwg`/`TRANSFORMER TWO WINDING GENERAL.dwg` 插入后导出截图肉眼确认，画出来的正是标准的断路器（带×标记）、隔离开关（带接地符号的折线）、双绕组变压器（两个相切圆）单线图符号——**说明 `insert_block` 不用改代码就能直接用这套真实的国标电气符号库**，之前 #26 想要的东西缺的不是代码，是真实符号数据，现在有了。

**实现**：新增 `symbol_library.json`（19 个符号的中英文名 -> 相对文件名目录，`base_dir` 存本机绝对路径）+ `cad/symbol_library.py`（解析出绝对路径列表，数据集不在本机时老实返回空数组而不是报错）+ MCP 工具 `list_symbol_library`（现在总共 29 个工具）。**符号本体（.dwg 文件）不提交进仓库**——这是用户自己收集的外部数据集，来源不明确能否自由再分发，仓库里只存路径目录。

**端到端验证**：真实 MCP 协议依次调 `list_symbol_library` → 按中文名"避雷器"在返回的目录里找到对应文件 → `insert_block` 用解析出的路径插入，全程成功。

**后续**：`UnderstandingCircuitDiagrams-VQA` 那批真实 110kV 变电站图纸，以及 206Origin 里其他海量的 CAD 图纸（比如「国家标准图集-电气图例」「电气符号库GB4728」等目录），都还有进一步利用空间（更多真实图纸样例、更全的符号库），先记在这里，作为后续如果需要可以再深挖的方向，这次没有全部处理。

## 2026-07-11（续七）：补 `new_drawing` 工具——补上一个安全缺口

用户想要一份"现在能测什么"的功能清单和提示词，好在网页 UI 里试。给之前发现一个安全缺口：之前所有写操作工具都是直接作用在"当前活动文档"上，但 AI 大脑自己没有工具能主动新建一张空白图纸——之前每次做实验性验证都是我自己手动写脚本检查 `document.Name`，现在真要把提示词交给用户去随便试，得让 AI 自己就能做这个安全检查，而不是全靠用户记得先手动新建文件。

**实现**：`state.py` 新增 `new_document()`（复用已有的 `CADConnection.new_document()`），`tools/document_tools.py` 新增 `new_drawing` MCP 工具，描述里写明"做实验性绘图操作前建议先调用这个"。现在总共 **30 个工具**。

**验证**：`asyncio.run(mcp.list_tools())` 确认工具已注册且总数变为 30；直接调用 `state.new_document()` 确认能正常切到新文档（`Drawing19.dwg`）。

## 2026-07-11（续八）：排查用户反馈的"复杂图纸质量差"——中文标注变问号 + 图块拼接没有对齐依据

用户用续七的测试提示词跑了「综合场景」那条（断路器+变压器+连接线+"10kV 进线"标注），截图显示标注文字变成了"10kV ??"，图块和连接线之间也明显没对上（连接线两端悬空，没有真正碰到图块的边缘）。

**排查过程**（没有直接猜，逐层实测排除）：
1. 先怀疑是 MCP/LLM 那层的编码问题（本项目之前踩过 conda run 在 GBK 控制台下的 `UnicodeEncodeError`），直接绕开 LLM/MCP，用 Python 脚本调 `cad/controller.py` 里的 `draw_text` 传中文字符串，读回 `TextString` ——**排除**：把结果写到 UTF-8 文件里读回（不经过控制台 print，避免二次踩同一个控制台编码坑），确认 `TextString` 存的就是完整正确的"10kV 进线测试"，数据链路（COM BSTR 编解码）没有问题。
2. 真正原因：`draw_text`/`draw_mtext` 之前都没指定 `TextStyle`，走的是 AutoCAD 默认的 "Standard" 样式——查了一下这个样式的字体文件是 `txt.shx`，这是一个只有 ASCII 字形的老式 SHX 形文件字体，没有中文字形，AutoCAD 渲染时遇到它不认识的字形就画成问号占位符。文字数据本身没坏，只是选错字体，视图里自然显示成"10kV ??"。
3. 图块/连接线对不上：`query.py` 之前完全没有暴露任何"实体边界框"信息，`insert_block`/`draw_line` 的调用方（不管是我还是上层 LLM）只能凭插入点瞎猜图块实际占多大、边缘在哪，写连接线坐标全靠拍脑袋——用真实场景验证：断路器图块的真实包围盒是 x∈[-3.65,1.5]，变压器是 x∈[193.25,206.75]，之前画的连接线是 (50,0)→(150,0)，两头分别悬空约 48 和 43 个单位，完全对不上图块边缘。这是缺一个"查询实体真实占用空间"的工具导致的，不是坐标计算错了，是根本没数据可算。

**修复**：
- `cad/controller.py` 新增 `_ensure_cjk_text_style()`：get-or-create 一个叫 `MCP_CJK` 的文字样式，`TextStyle.SetFont("SimSun", False, False, 134, 0)`（134=GB2312 字符集），`draw_text`/`draw_mtext` 现在都默认用这个样式，中英文混排都能正常显示，不用调用方关心字体。
- `cad/query.py` 的 `_entity_summary()` 新增 `bounding_box`（`entity.GetBoundingBox()` 的 min/max 点），所有实体类型（图块引用/线/文字等）的 `get_entity`/`query_entities` 现在都会带上真实包围盒，之后画连接线前可以先查一下图块的边界框再算坐标，不用再瞎猜。

**验证**：用真实 AutoCAD 连接测试，`draw_mtext` 写入"10kV 进线测试"后 `get_entity` 读回确认样式生效、文字正确；对已有的断路器/变压器图块和连接线跑 `get_entity`，确认 `bounding_box` 字段返回的真实坐标和前面手工核对的一致。`pytest` 全量跑过，无回归。

**尚未解决**：`bounding_box` 只是给了数据，图块之间的自动对齐/连线仍然要靠 LLM 自己算（或者未来再加一层"自动布线"辅助工具）；旋转角度让符号朝向匹配连接方向、图块内部"接线端子"位置（不是包围盒边缘，而是符号定义里预留的电气连接点）目前也还没有专门支持——这些记为后续可能要做的方向，这次先解决"数据缺失"和"字体缺失"这两个更直接、更能立刻验证对错的问题。

## 2026-07-11（续九）：[#13] `save_drawing` 加保护，避免误覆盖用户真实图纸

用户反馈中文和布局问题有改善后，让我"继续开发，完善项目"。查了一下开放 issue 列表，`#13` 是 CLAUDE.md「安全注意事项」里明确点名过的隐患：`save_drawing` 之前是裸调用 `document.SaveAs(file_path)`，没有任何保护——如果 AI 传的 `file_path` 恰好和用户当前文档的原始路径相同，会直接覆盖用户正在编辑的真实图纸，之前完全没有拦截。

**修复**（`cad/controller.py::save_drawing`）：
- 校验扩展名在 AutoCAD SaveAs 支持的格式内（`.dwg`/`.dxf`/`.dwt`/`.dws`），否则报友好错误而不是等 COM 层抛一个晦涩的报错。
- 校验目标目录存在。
- 新增 `overwrite: bool = False` 参数：如果 `file_path` 和 `document.FullName`（当前文档原始路径，大小写不敏感比较）相同且 `overwrite=False`，直接拒绝并报错说明原因；确实要覆盖原文件时显式传 `overwrite=True`。`tools/document_tools.py` 的 `save_drawing` 工具签名同步更新。

**验证**：用真实 AutoCAD 连接测试了 5 种情况——错误扩展名拒绝、目标目录不存在拒绝、正常另存成功、二次存到同一路径不加 overwrite 被拒绝、加 overwrite=True 后成功覆盖——全部符合预期。中途踩了个环境坑：临时测试文件放在 Windows 短文件名路径（`LIUYAN~1`）下时 `SaveAs` 会报错，换成普通路径（`C:\Temp\`）后正常——这是本机临时目录短路径命名的固有怪癖，和这次改的代码无关，记录一下避免以后重复排查。`pytest` 全量跑过，无回归。GitHub `#13` 已关闭。

## 2026-07-11（续十）：[#25] 按区域查询实体（`query_entities_in_region`），过程中揪出一个 COM 层的"首次调用"坑

继续做 `#25`：`query_entities` 一直是全表扫描 ModelSpace，复杂图纸实体一多，"查一下这个区域里有什么"只能靠遍历全部实体自己算相不相交，效率低也麻烦。AutoCAD COM 自带 `Document.SelectionSets` + `SelectionSet.Select(Mode, Point1, Point2)` 正好是做这件事的原生 API，之前没用过。

**踩坑排查（`AcSelect` 枚举值没有官方文档能直接查到确切数字，全靠实测）**：
1. 拿三条已知位置关系的线（完全在框内/框边界穿过/完全在框外）实测 `Select` 的 `Mode` 参数 0~7，配合 WebSearch 找到的 Autodesk 文档片段（`Fence=2`/`WindowPolygon=6`/`CrossingPolygon=7`，这三个传单点对坐标会报"参数 Mode 无效"，和实测报错的 mode 2/6/7 完全对上），反推出 `Window=0`、`Crossing=1`（`Mode=1` 在所有测试里都精确匹配"完全在框内 + 边界相交"的预期行为）。
2. 意外发现一个更麻烦的问题：不管 `Window` 还是 `Crossing`，**一个 SelectionSet 对象的第一次 `Select()` 调用有概率错误返回空集合**（连续跑 10 次同样的调用，第 1 次返回 0，第 2~10 次全部正确）——不是坐标算错，是 COM 层某种一次性的初始化时序问题（这个项目里已经不是第一次遇到"刚创建的 COM 对象/刚建立的状态第一次访问会出错"这类坑了，参见 `connection.py` 里 `_wait_for_document` 的类似问题）。用真实 MCP 协议跑的验证脚本也复现了同样的现象。
3. **规避方法（已验证 8 次全部通过）**：在同一个 SelectionSet 上把 `Select()` 调用两遍，只用第二次的结果——不知道底层具体机制，但这个规避方式在反复测试里 100% 稳定。

**实现**：`cad/query.py` 新增 `query_entities_in_region(corner1, corner2, mode="crossing", entity_type=None)`，`tools/query_tools.py` 注册同名 MCP 工具（现在总共 **31 个**工具）。`architecture.md` 工具清单和"开放问题"章节同步更新（`#25`、`#26` 两条 roadmap 划掉）。

**验证**：真实 MCP 协议全量跑通（小窗口只选中框内的线，大窗口选中全部线，按 `entity_type` 过滤正常），`pytest` 无回归。GitHub `#25` 已关闭。

## 2026-07-11（续十一）：[#27] 图块属性批量填报/校核

用户让我按顺序把剩下的 backlog 依次做完。这次做 `#27`：`get_block_attributes`/`set_block_attribute` 之前一次只能查/改一个图块，复杂图纸里成百上千个设备图块要批量填报/校核完全没有高层封装。

**实现**（`cad/query.py`）：
- `bulk_get_block_attributes(object_ids=None, block_name=None)`：按 ObjectID 列表或图块名批量取属性，都不传就是图纸里所有带属性的图块引用，返回 `{object_id: {tag: value}}`。
- `bulk_set_block_attributes(updates: list[dict])`：批量设置 `[{"object_id","tag","value"}, ...]`，单条失败（ObjectID 不存在/图块没这个 tag）不影响其它条，每条都返回 `status="ok"/"error"`——不会让一整批调用因为一条坏数据直接抛异常中断。
- `validate_block_attributes(required_tags, block_name=None)`：校核必填属性是否都存在且非空，只返回有问题的图块（缺失的 tag 列表 + 空值的 tag 列表）。

`tools/query_tools.py` 注册 `bulk_get_block_attributes`/`bulk_set_block_attributes`/`validate_block_attributes` 三个 MCP 工具（现在总共 **34 个**工具）。

**验证**：一开始想直接拿之前 `#26` 那批真实电力符号（断路器等）测试，结果发现这批 .dwg 符号本身其实没有定义属性（`HasAttributes=False`）——符号库目录名叫"带属性的块集合"但不代表每个文件都真带属性，这是数据集本身的情况，不是代码问题。于是改用 COM 现场定义一个带 `DEVICE_ID` 属性的临时测试图块（`Blocks.Add` + `Block.AddAttribute`），插入两份引用，跑通真实 MCP 协议全流程：按 ObjectID/按图块名批量查、批量设置（含一条故意传坏 ObjectID、一条故意传不存在的 tag，确认失败条目被单独标记而不影响其它条）、清空其中一条属性后校核出"缺失 tag + 空值 tag"都能正确识别。`pytest` 无回归。GitHub `#27` 已关闭。

## 2026-07-11（续十二）：[#11] 大图纸查询性能优化——两个数量级的实测提升

用户让我按顺序继续做剩下的 backlog，这次是 `#11`。`cad/query.py` 文件开头原来的注释写着"classic AutoCAD COM has no ObjectIdToObject like the .NET API"——这次实测发现这个假设是错的，AutoCAD ActiveX 其实是有的，只是之前没试过。

**实测验证（真实 AutoCAD 连接，不是猜）**：
1. `Document.ObjectIdToObject(object_id)`：直接测试确认存在且可用，传无效 ID 会抛 `pythoncom.com_error`（可以转成原来的 `KeyError` 语义，行为不变）。用 1500 条实体的图纸做基准：全表扫描找中间那条要 **3.4266s**，`ObjectIdToObject` 只要 **0.0045s**——快了约 760 倍。
2. `SelectionSet.Select` 支持按 DXF group-0 类型过滤（`FilterType`/`FilterData` 参数），比 Python 侧逐个实体调 `.ObjectName` 判断快得多。同样 1650 个实体（1500 线 + 150 圆）里挑圆：原来的全表扫描+过滤要 **79.192s**，SelectionSet 过滤只要 **10.971s**——快了约 7 倍。
3. **DXF 类型名不能直接从 ActiveX 的 `ObjectName` 猜**（比如 `AcDbBlockReference` 对应的 DXF 类型是 `"INSERT"` 不是 `"BLOCKREFERENCE"`），一个个建了真实连接实测才能确认映射表：`AcDbLine`→`LINE`、`AcDbCircle`→`CIRCLE`、`AcDbArc`→`ARC`、`AcDb2dPolyline`→`POLYLINE`（顺带发现 `draw_polyline`/`draw_rectangle` 生成的是老式 `AcDb2dPolyline` 而不是新式 `LWPOLYLINE`）、`AcDbText`→`TEXT`、`AcDbMText`→`MTEXT`、`AcDbHatch`→`HATCH`、`AcDbBlockReference`→`INSERT`、`AcDbAlignedDimension`→`DIMENSION`。

**实现**：
- `_find_entity`（`get_entity`/`delete_entity`/`move_entity`/`rotate_entity`/`copy_entity`/`scale_entity`/`mirror_entity`/`get_block_attributes`/`set_block_attribute` 等 9 个方法共用的查找入口）改用 `ObjectIdToObject`，全表扫描彻底去掉。
- `query_entities(entity_type=...)` 传入的类型如果命中 `_ENTITY_TYPE_TO_DXF_FILTER` 映射表，就走 `SelectionSet` 原生过滤；不在表里的类型名（或不传类型）回退到原来的全表扫描——保证任何输入都不会查不到，只是命中已知类型时更快。用的还是 `query_entities_in_region` 那次踩过的"SelectionSet 第一次 Select 偶发返回空集合"规避写法（连续 Select 两次）。

**验证**：真实 MCP 协议跑通 `get_entity`/`query_entities`（含类型过滤、无过滤、未收录类型三种情况）、不存在的 ObjectID 正确抛 `KeyError`、`move_entity`/`copy_entity` 等依赖 `_find_entity` 的操作全部正常。`pytest` 无回归。GitHub `#11` 已关闭。

## 2026-07-11（续十三）：[#10] 补充 pytest 自动化测试覆盖

`tests/` 之前只有 `test_connection.py` 一个文件（就测了个连接）。这次把 `cad/controller.py`/`cad/query.py` 的核心能力补上真实自动化测试，遵循 CLAUDE.md 的安全规则——不是 mock，是接真实 AutoCAD 连接跑，但连不上就 `pytest.skip`，且每个测试都在 `new_document()` 出来的全新空白图纸上跑，绝不会碰用户当前打开的真实图纸。

**新增**：
- `tests/conftest.py`：`cad_connection`（session 级，连不上就 skip 掉所有依赖它的测试）+ `scratch_doc`（每个测试前强制切到新空白图纸）两个共用 fixture。
- `tests/test_controller.py`：`draw_line`/`draw_circle`/`draw_arc`/`draw_rectangle`/`draw_polyline`/`draw_hatch`/`add_dimension`/`create_layer`+`set_layer_properties`/`insert_block`+`list_blocks`，以及专门验证 `draw_text`/`draw_mtext` 确实用了 `MCP_CJK` 样式（防止"中文变问号"那个 bug 回归）。
- `tests/test_query.py`：`query_entities`（无过滤/按类型过滤/未收录类型回退）、`get_entity`/`delete_entity`（含查不存在的 ObjectID 正确抛 `KeyError`）、`move`/`rotate`/`copy`/`scale`/`mirror_entity`、`query_entities_in_region`（区域内 vs 区域外 + 非法 mode 报错）、单个/批量图块属性 get/set/validate。
- `tests/test_document.py`：`save_drawing` 的三种安全校验（错误扩展名/目标目录不存在/同路径覆盖保护）。
- `tests/test_symbol_library.py`：`symbol_library.list_symbols()` 不需要真实 AutoCAD 连接，纯单元测试。
- `tests/test_server_registration.py`：工具注册也不需要连接 AutoCAD（`server.py` 只是装饰函数），校验 34 个工具全部注册成功，覆盖所有分组。

**踩坑**：第一次全量跑通过，但连续跑第二遍时 `test_save_drawing_overwrite_protection` 报了一个 COM 错误（"保存文档时出错"）——原因是这个测试原来用固定文件名，而这台机器上 AutoCAD 连接是跨 pytest 运行复用的长连接，`new_document()` 只切到新文档、不会关掉旧文档，上一轮测试保存过的那个文档还开着占用同一个路径，这一轮再 `SaveAs` 到同名路径就冲突了——不是被测代码的 bug，是测试之间的资源冲突。改成每次跑都用 `uuid4` 生成唯一文件名后，连续跑 3 遍都是 26 个测试全过，没有再复现。

**验证**：`pytest tests/ -v` 连续 3 次全量运行，均 26 passed，无回归无 flaky。GitHub `#10` 已关闭。

## 2026-07-11（续十四）：[#12] Claude Desktop 接入验证——原来当前会话本身就是现成的验证环境

`#12` 要的是"接入 Claude Desktop，做自然语言端到端验证"。查 `claude_desktop_config.json` 发现 `autocad-mcp` 已经注册好了（`command` 指向 conda 环境里的 python.exe，`args` 是 `-m autocad_mcp.server`，走默认 stdio），而且**当前这个 Claude 会话本身就是通过这份配置连上 autocad-mcp 的**——也就是说不需要另外找个 Claude Desktop 窗口去验证，直接在这个会话里用已经加载好的 `mcp__autocad-mcp__*` 工具做的任何操作，就是 `#12` 要验证的那条链路本身。

**验证**：依次调用 `new_drawing` → `draw_circle`（半径 25 的圆）→ `draw_mtext`（"Claude Desktop 端到端验证"，中文）→ `query_entities` 读回，全部通过真实 MCP 协议（stdio）走通，坐标、文字内容都正确。GitHub `#12` 已关闭。

**过程中意外发现两个值得记录的问题**：
1. 验证完之后想顺手截图存证，调 `export_current_view` 超时了。查了一下发现这台 AutoCAD 实例这次会话里累积开着 **136 个文档**（`Drawing1.dwg` 到 `Drawing136.dwg`，全是这次会话反复测试 `new_document()`/`new_drawing` 留下的空白文档，`FullName` 全是空，没存过盘）——AutoCAD 被这么多文档拖慢，导致原本 30s 的导出超时窗口不够用了。这是这次超长测试会话自己攒出来的资源问题，不是 `export_current_view` 代码本身的 bug。问过用户后确认清理，关掉了全部 136 个（`Document.Close(False)`，确认都没有真实文件路径，不是用户的东西）只留一个新建的空白图纸，之后导出立刻恢复正常。
2. 清理过程中还发现一个真实的健壮性问题：清理脚本是从一个新建的 `CADConnection`（`GetActiveObject` 连的同一个 AutoCAD 进程）里关掉文档的，而**当前这个 MCP 服务器进程自己缓存的 `document`/`model_space` COM 引用**是指向被关掉的那个文档的——被关掉之后，服务器进程再调用工具就报 `(-2147417848, '被调用的对象已与其客户端断开连接。', ...)`（RPC_E_DISCONNECTED），需要手动再调一次 `new_drawing` 强制刷新 `state.py` 里的连接单例才恢复。也就是说：如果 AutoCAD 里的活动文档被别的途径（比如用户自己在 AutoCAD 界面里关掉）意外改变，服务器不会自愈，会一直报底层 COM 错误直到有人手动调 `new_drawing`。这个不在这次 `#12` 的范围内，已经拆成一个单独的后台任务建议（`task_373b8e0b`）留给后续处理，不在这次顺便改。

## 2026-07-11（续十五）：[#16] 网页聊天支持流式响应

用户让我按顺序继续做剩下的 backlog，`#16` 是"网页聊天支持流式响应"。之前的 `/api/chat` 是等整个 agent loop（可能包含好几轮工具调用）跑完才一次性返回，前端只能靠一个"思考中...(已等待 N 秒)"的计时器撑场面，看不到具体在干什么。

**实现**：
- `web/backend/providers/base.py`：`LLMProvider` 新增抽象方法 `chat_stream()`，逐步 yield `{"type": "text_delta", "text"}`，正常结束 yield 一次 `{"type": "done", "tool_calls": [...]}`。
- `web/backend/providers/anthropic_provider.py`：用 `client.messages.stream()`（`async with` + `stream.text_stream` + `stream.get_final_message()`，这是当前 Anthropic Python SDK 文档里的推荐流式写法，不是训练数据里可能过时的旧模式，专门用 claude-api 技能核对过）。
- `web/backend/providers/openai_provider.py`：用 `stream=True`，累积每个 chunk 的 `delta.content`（文字）和 `delta.tool_calls`（按 `index` 累积，因为 `arguments` 是分片到达的）。`DoubaoProvider` 直接继承，不用改。
- `web/backend/agent_loop.py`：新增 `run_turn_stream()`，逐步 yield 结构化事件（`text_delta`/`tool_call`/`tool_result`/`error`/`done`），工具调用之间也能看到进度。
- `web/backend/app.py`：新增 `POST /api/chat/stream`，用 FastAPI 的 `StreamingResponse`（`text/event-stream`）包一层 SSE 格式。
- `web/frontend/app.js`：把之前的"思考中...计时器"换成真正逐字追加的回复文本，工具调用/结果单独显示成一行灰色小字状态提示。

**排查过程（这次踩的坑比预想的深很多）**：用真实浏览器测试（起了 AutoCAD MCP 的 `--http` 服务 + 网页后端两个真实进程，故意不填 API Key 触发一个真实的认证失败），前端显示完全正确（错误信息干净地展示出来），但服务端日志每次都报一个奇怪的 `RuntimeError: Attempted to exit a cancel scope that isn't the current tasks's current cancel scope`。为了搞清楚这是不是我自己代码的 bug，做了一系列最小化对照测试（不经过 Anthropic/OpenAI，纯用 FastAPI + httpx + 一个什么都不做的 `async with`）：

1. 确认了触发条件——一个异步生成器只要"某次 `yield` 之后，同一个生成器帧里后面又抛了异常并从这个生成器传播出去"，被 Starlette 的 `StreamingResponse` 消费时就必定触发这个 `RuntimeError`，和具体用没用 httpx/Anthropic SDK 完全无关，纯粹是这条"异步生成器链路 + Starlette 自带的 anyio 任务组"本身的限制（用几个只包含普通 `async with`/无关异常的最小化测试复现过好几次）。
2. 但改成"异常在 with 块内部就地捕获、绝不 `raise`、只把结果转成普通 `yield` 出去的字典值"之后，真实场景里**还是**复现了同一个报错——而这次做了更细的最小化对照测试才发现：单独测 httpx 出错、单独测 Anthropic SDK 认证失败、两层生成器嵌套（模拟 `event_generator → run_turn_stream → chat_stream` 这条真实链路）分别测都**没有**复现，但完整的真实应用（`uvicorn web.backend.app:app`）里就是会复现——说明触发条件比我目前验证到的更微妙，大概率是这几层东西按真实应用的组合方式叠加时才会触发，具体机制没有继续深挖下去（投入产出比已经不划算，这是 Starlette/anyio 版本组合本身的一个边角问题）。

**结论**：这个报错**只在服务端日志里出现，不影响任何用户可见的行为**——每一次测试，前端收到的响应内容都完整、正确（用真实浏览器点击发送、读页面文字、看网络请求验证过好几轮）。过程中顺手修了两个真实的、值得保留的问题：`AnthropicProvider`/`OpenAIProvider` 之前每次调用都新建一个 `AsyncAnthropic`/`AsyncOpenAI` 客户端却从来不关闭（`chat()` 和 `chat_stream()` 都是），现在统一用 `async with` 显式关闭，不再依赖垃圾回收器兜底；`run_turn_stream()` 里每个可能失败的调用（建 provider、连 MCP、调工具）都各自独立 try/except，出错立刻 `yield` 错误事件 + `return`，不再用一个大 try 包住跨越多个 yield 的整段逻辑。这两处修复本身是有意义的代码质量改进，但没能让那个服务端日志噪音消失——如实记录，没有假装"完全修好了"。

**验证**：真实浏览器测试（起 `autocad-mcp --http` + `web-backend` 两个真实进程，`.claude/launch.json` 补了 `autocad-mcp-http` 这个新配置项）反复点击发送按钮，`read_page`/`get_page_text` 确认前端正确显示错误信息、正常状态提示行；`read_network_requests` 确认 `/api/chat/stream` 返回 `200 OK`；服务端 `preview_logs` 确认请求-响应本身完整。`pytest` 全量跑过，26 个测试全过，无回归（AutoCAD 那边真实连接测试跑完之后解释器退出时有一个和这次改动无关的 COM 清理相关的崩溃堆栈，出现在"26 passed"之后，不影响测试结果本身）。

**尚未解决**：服务端日志里这个 `RuntimeError` 噪音本身没有连根拔起，只是确认了不影响功能正确性。如果以后遇到真实的流式响应异常中断（不只是日志噪音），需要重新审视这个问题。GitHub `#16` 按功能已实现的标准关闭，但在 issue 里如实注明这个已知的日志噪音。

## 2026-07-11（续十六）：本地 VQA 模型服务端到端验证（用真实变电站图纸）

用户启动了本地 VQA 模型服务（`vqa_api_server.py`，端口 8933）之后，让我验证一下。先 `vqa_service_status` 确认服务已加载（`internvl3-8b-power-vqa-lora-v9_1-checkpoint800`），然后想直接用当前会话已连接的 `mcp__autocad-mcp__ask_drawing_vqa` 工具测——结果连续两次都报 `MCP error -32001: Request timed out`。

**排查**：这个超时不是 VQA 服务本身的问题——`vqa_tools.py` 里 `ask_drawing_vqa` 自己用的 httpx 超时是 180 秒（模型 4bit 量化单题推理本来就要 90~130 秒），但当前这个 Claude 会话自己的 MCP 客户端（走 stdio，由 harness 驱动，不是这个项目代码控制的东西）显然有一个更短的默认请求超时，先于 180 秒触发。绕开 MCP 层，直接用 Python 脚本 `httpx.post` 打 VQA 服务的 `/vqa` 接口（超时设够 180 秒），确认服务本身完全正常工作：

1. 先测了一张当前 AutoCAD 导出的空白 scratch 图纸截图（`export_current_view` 导出）——耗时 178.4s，模型正确回答"这张图没有任何绘制内容，是纯空白的画布"，证明整个转发链路本身没问题。
2. 再测了一张真实数据集里的图（`UnderstandingCircuitDiagrams-VQA/origin-data` 目录下一张国家电网 110kV 变电站"电气主接线图"的 PNG）——耗时 130.5s，问"这张图里画的是什么设备，母线是什么接线方式？"，模型回答"这是120kV变电站的GIS母线，采用单母线分段接线，一共两段母线"——语义连贯、领域相关，说明这个针对电力工程图纸微调过的模型确实能看懂真实变电站图纸并给出合理回答（电压等级说的是 120kV 不是 110kV，可能是模型本身的小误差，不影响这次验证"整条链路能不能跑通、回答质不质"的目的）。

**结论**：`ask_drawing_vqa` 工具本身（HTTP 转发 + 本地 VQA 服务）功能完全正常，用真实变电站图纸验证过给出的回答是有意义的领域回答。**这次验证的是本地 VQA 模型（用户口头说的"#17"），不是 GitHub `#17` issue 字面上写的"网页 UI vision 图片上传 + 画图"那个功能**——那个仍然需要真实 Anthropic/OpenAI API Key 才能测，和 `#14`/`#15` 卡在同一个原因上，这次没有动，GitHub `#17` 保持打开。

## 2026-07-13：用真实豆包 API Key 跑通完整流式响应（成功路径），并纠正续十五里一个错误结论

用户新建了 `.env`（`doubao_base_url`/`doubao_model_name`/`doubao_api_key`，测试用的真实豆包接口凭证），说可以拿来开发测试。**先做的第一件事**：发现 `.env` 当时没被 `.gitignore` 忽略，赶在它被 git 追踪之前把 `.env` 加进 `.gitignore` 并提交推送，避免真实 Key 被误提交。

**用途**：`#16` 流式响应实现完之后，之前所有真实浏览器测试都只测过"认证失败"这一条错误路径，从没验证过"真的连上一个能用的模型、跑出完整的流式回复+工具调用"这条成功路径。用真实豆包 Key 写了个脚本（直接读 `.env`、程序化调用 `POST /api/chat/stream`，不经过浏览器表单——按项目安全规则，API Key 不能由我操作浏览器填进网页输入框，但脚本里当参数值传给自己项目的 API 是两回事）跑了一遍"新建一张空白图纸，然后画一个圆心在原点、半径为15的圆"：完整收到了 `tool_call(new_drawing)` → `tool_result` → `tool_call(draw_circle)` → `tool_result` → 一连串真实的逐字 `text_delta`（豆包大模型对着刚才的工具执行结果生成的自然语言总结）→ `done`，整条 SSE 事件流结构、内容都完全正确，`OpenAIProvider.chat_stream()`（豆包走这条继承路径）的 tool_call 累积和文字增量转发逻辑，真实场景下第一次得到完整验证。

**纠正续十五的结论**：这次成功路径的真实测试里，服务端日志**同样**报了那个 `RuntimeError: Attempted to exit a cancel scope that isn't the current tasks's current cancel scope`——续十五当时因为只测过错误路径，错误地把这个报错和"出错时的 yield/raise 处理方式"关联在一起，写成"这个报错只在...出错路径"，这个说法不准确，如实更正：**这个报错和请求是否成功、代码里怎么处理异常都没关系，是这个环境下 Starlette StreamingResponse 处理这类多层生成器嵌套 + 真实网络 I/O 时的一个通用副作用**，成功和失败路径都会触发，但两种情况下响应内容本身都是完整、正确的，不影响功能。仍然只是服务端日志噪音。

## 2026-07-13：新增"真实图纸参考"能力——解决"画出来的电力图不像"

用户反馈"画出来的电力图还是很不像"，问能不能用之前给的那批真实 DWG 数据（ground truth）让模型学会怎么画。跟用户对齐过方向：不训练/微调大模型（不符合 CLAUDE.md"不自己搞 NLP/训练层"的架构原则，Claude/豆包这类第三方模型也没法微调），而是从真实图纸里提取结构化的布局数据，做成一个新工具，让 AI 画图前先"查"一下真实图纸里符号是怎么摆放、连接的，用真实范例代替瞎猜坐标——跟 `#26` 解决"有没有标准符号"是同一个思路的延伸，这次解决"符号该怎么摆"。

**实现**：
- `reference_drawings.json`：真实参考图纸目录（完整图纸，不是单个符号），`base_dir` 指向 206Origin 数据集里"14-配电房设计CAD施工图"目录，先收了 4 张有代表性的真实主接线图（35kV 变电站改造、小型水电站、三峡左岸/隔河岩水电站电气主接线图）。图纸本体不提交仓库，跟 `symbol_library.json` 一个原则。
- `cad/reference_library.py`：`list_reference_drawings()` 解析目录；`analyze_reference_drawing(connection, file_path, entity_type=None, max_entities=500)` 用 `Documents.Open(file_path, True)` 只读打开真实图纸（不影响当前正在编辑的文档），遍历 ModelSpace，复用 `query.py` 里现成的 `_entity_summary()` 提取每个实体的类型/坐标/包围盒，返回给 AI 参考。
- `tools/reference_tools.py`：注册 `list_reference_drawings`/`analyze_reference_drawing` 两个 MCP 工具（现在总共 **36 个**工具）。

**踩坑（真实图纸和之前用的标准符号库很不一样）**：
1. 用真实文件测的时候发现，`35kV变电站改造主接线及总平面.dwg` 全图 2912 个实体，**图块引用（AcDbBlockReference）只有 1 个**，而且那 1 个还是"电气图签"（图纸标题栏），不是电路符号——绝大多数"符号"其实是用直线/圆/圆弧这些原始图元手工画出来的，不是插入的图块。这意味着这个工具不能只看图块引用，必须把所有图元类型的真实坐标都提取出来给 AI 参考，一开始的设计假设（"参考图纸=一堆图块引用"）是错的，已经改成提取全部实体类型。
2. `Documents.Open()` 会把新打开的参考图纸变成当前活动文档，分析完得切回原来的文档——第一次实现只做了"切回去"（`app.ActiveDocument = original_active`），忘了 `state.py` 里 `connection` 自己缓存的 `document`/`model_space` COM 引用在切换活动文档之后会失效，导致分析完之后紧接着调用其它工具直接报 `AttributeError`。这是这个项目里已经出现过好几次的"缓存的 COM 引用会失效"这类坑（和 #12 发现的连接自愈缺口是同一类问题，这次是自己的新代码直接踩上了）——修复：分析完之后主动调用 `connection._wait_for_document(...)` 强制刷新缓存，不留给调用方自己踩坑。
3. 测试过程中不小心让 AutoCAD 又累积了 99 个空白测试文档（这轮功能开发反复调试产生的），导致 `pytest` 连续几次运行都有随机不同的测试在 COM 资源紧张时偶发失败（单独跑都能过）。问过用户后确认清理，关掉了全部 99 个只留一个新建的空白图纸，之后 `pytest` 连续跑两遍都稳定 26 个测试全过。

**验证**：真实 MCP 协议跑通 `list_reference_drawings`（返回 4 条目录）→ `analyze_reference_drawing`（对 35kV 变电站图纸提取真实坐标，`total_entity_count=2912`，按 `max_entities` 截断返回；按 `entity_type="AcDbBlockReference"` 过滤能精确挑出那 1 个图签图块）→ 分析完之后确认当前 scratch 文档仍是活动文档、`connection` 状态正常，没有踩上第 2 点那个坑。补充了 `tests/test_reference_library.py`（目录列表纯单元测试 + 真实提取测试，数据集不在本机时 skip）。`pytest` 全量 26 个测试通过，无回归。

## 2026-07-14：数据管道第一步——真实图纸批量转训练样本，外加两个真实踩坑（老式多段线坐标步长、图纸缺字体）

用户上一轮问"能不能用真实图纸训练画图模型"，讨论后定了方向：不训练/微调第三方大模型（不符合项目架构原则），而是把真实图纸的实体机械转换成"重建它需要调用哪个 MCP 工具"的记录——转换不需要人工标注，真实坐标本身就是最准确的标签。这次做数据管道的前两步：批量抽取 + 实体转工具调用序列。

**实现**：
- `cad/training_export.py`：`entity_to_tool_call(entity)`，把 COM 实体转换成 `{"tool": 工具名, "args": {...}}`，参数名严格对齐 `tools/drawing_tools.py` 里各工具的真实签名（拍平的 x/y/z，不是嵌套列表），产出的样本可以直接当 MCP 工具调用参数回放。支持 `AcDbLine`/`AcDbCircle`/`AcDbArc`/`AcDbPolyline`/`AcDb2dPolyline`/`AcDbBlockReference`/`AcDbText`/`AcDbMText`，不认识的类型或提取失败返回 `None`（调用方跳过，不是致命错误）。
- `scripts/build_training_dataset.py`：批量扫描一个目录下的真实 DWG，每个文件产出一行 JSONL（`file`/`entity_count`/`converted_count`/`tool_calls`），支持断点续跑（已处理过的文件自动跳过）。
- 用户反馈真实数据集里混了广告/水印文字（举的例子："星欣设计图库"）——`training_export.py` 加了 `_is_ad_noise()` 精确短语匹配，命中的文字实体直接跳过不进数据集。**踩坑**：一开始想用宽泛关键词"QQ"过滤，测试数据里发现会误伤"1QQ"这种正常的设备/继电器位号（真实图纸里大量这类简写位号），改成只匹配完整、明确是广告的短语，不用单个宽泛关键词。

**两个新真实坑（都是本次实测发现，不是猜的）**：
1. **老式多段线的坐标步长和新式的不一样**：`_extract_polyline_points` 一开始假设 `Coordinates` 都是"每个顶点 2 个数（x,y）"，用本项目自己的 `draw_polyline` 画一个三角形转换测试时，读出来的坐标完全对不上——实测确认 `AcDb2dPolyline`（老式重量级多段线，`draw_polyline` 自己画出来的就是这种）的 `Coordinates` 其实是"每个顶点 3 个数（x,y,z）"，而 `AcDbPolyline`（现代轻量级/LWPOLYLINE，真实图纸里绝大多数是这种）才是 2 个数。已经按实体类型区分步长，两种都验证过正确。
2. **打开真实图纸中文不显示**：用户反馈开真实图纸时中文变问号，排查发现是图纸引用的自定义大字体（`HZ`/`ST64F`/`khz`/`HZFS`/`HZFS1`/`hztxt` 等）本机没装。用户提供了两个字体资源：一个"万能字体"单文件、一个"CAD字体大全"（4623 个文件的完整字体库）。写了 `scripts/fill_missing_fonts.py`：扫描真实图纸收集 `fontFile`/`BigFontFile` 引用，从字体库里找到真名字体，只新增缺失的、绝不覆盖 AutoCAD 目录下任何已存在文件。**中途一个真实翻车**：图省事先用万能字体假冒了 `HZ.shx`/`ST64F.shx`/`khz.shx` 三个名字（用户后来给了字体库里的真字体后换成真的）；脚本第一版还犯了一个更隐蔽的错——把 Windows 系统自带的 `simsun.ttc`（TrueType Collection，一个文件装了多个字体）改名当成 `SimSun.ttf`（单个 TrueType 字体）复制进 AutoCAD 目录，`file` 命令验证过这就是一次真实的格式冒充，及时发现并删除，同时把脚本改成扩展名必须精确匹配（不再跨扩展名冒充）+ TrueType 字体要在 AutoCAD 自己的 Fonts 目录**或** Windows 系统字体目录（`C:\Windows\Fonts`）任一处存在即可，不需要额外复制。这两次改动**只影响真实图纸打开时中文能不能正常显示，不影响训练数据本身**（`TextString` 属性读到的是图纸内部存的真实 Unicode 文字，跟渲染字体是否存在无关，这一点在续十五排查中文乱码问题时已经验证过）。凡是往 AutoCAD/Windows 字体目录写文件的操作都先问过用户再做。
3. **意外发现并修复了一个已上线工具的潜在 bug**：批量跑数据管道时复现了 `AttributeError('<unknown>.Close')`——这是 `Documents.Open()` 返回值不可靠这个老坑的另一种表现形式（这个项目里 `Documents.Add()` 的返回值也有过同样问题），只是这次连 `Close()` 都会踩到。之前 `reference_library.py::analyze_reference_drawing`（已经上线的 MCP 工具）没有做这层防护，只是运气好没在之前的测试里触发——这次把"打开重试+验证解析完成"和"关闭重试"都提炼成 `open_reference_drawing()`/`close_reference_drawing()` 两个共享函数，`analyze_reference_drawing`、`build_training_dataset.py`、`fill_missing_fonts.py` 三处统一复用，不再各自维护一份逻辑。

**验证**：`build_training_dataset.py` 对"小型水电站电气一次主接线图"目录跑通，产出真实 JSONL（比如一条真实记录：2 点直线 `draw_line` 参数完全对应图纸里的真实坐标）；`entity_count == converted_count` 对纯直线/多段线的文件做到 100% 转换率。新增 `tests/test_training_export.py`（噪声过滤 + 各实体类型转换，含多段线步长修复后的正确性验证）。`pytest` 全量跑通（有 1 次偶发的 COM 忙碌瞬时失败，单独跑通过，跟这批改动无关——这次会话末尾特意保留了 53 个只读打开的参考图纸文档没清理，AutoCAD 资源比较紧张，这类偶发失败在这台机器上是已知的、跟真实 bug 无关的噪音）。

**尚未做**：这只是数据管道的前两步（抽取 + 转换），"输入提示（instruction）从哪来"和"训练什么模型、怎么评估"这两个更大的问题还没展开，按之前讨论的方案，这些留给独立的机器学习项目决策。


## 2026-11-18：冻结 MCP 契约，统一 COM 后端与 STA 生命周期

- 从 `main@5e83798` 建立 `codex/backend-foundation`。保留开始时已有的 3 个 Web 文件修改及 4 个未追踪的数据脚本/交接文档，未纳入本轮修改或提交。
- 阅读项目分层、既有测试与 roadmap，先实施 CAD-01 的契约基线及 CAD-02/03 的 COM 基础。归档 roadmap 为设计草案，新增 backend 设计/状态、环境 JSON 和 36 项工具迁移矩阵；未将规划目标记为完成。
- 修复 query-first 时 controller 无条件新建第二条 connection 的问题。统一 backend/factory 和兼容 facade，既有算法不移动；32 个 CAD 工具的调用经白名单执行，参考图纸工具不再把 COM connection 取出工具层。
- 懒启动独立 STA 线程初始化/使用/释放全部 backend 原生对象，串行队列上限 64；只传普通数据，满队列和线程异常明确失败。关闭排空已接收任务，不保存、关闭图纸或退出 CAD；不自动重放失败写入。显式关闭后可重建，新建图纸刷新共享引用。
- 增加活动文档名称防护、原子替换 document/model_space 快照、参考图纸恢复失败后失效引用；这是旧 COM 的保守保护，不替代规划中的稳定文档会话、权限和 revision。
- MCP 服务共享后端按客户端会话计数，最后一位客户端退出才清理。新增回归确实发现了断连取消跳过 cleanup 的问题，改用 AnyIO cancellation shield 后通过，避免一个 HTTP 客户端断开关闭其他客户端的后端。
- 配置保留所有旧字段，backend 缺省 COM；选择尚未实现的 HTTP backend 会明确报错，不回退。MCP 8931 的 Streamable HTTP 与规划 Bridge 是两件事。
- 重构前运行的既有 8 项测试包含被误认为离线的集成测试，自动启动 AutoCAD 并在 fixture 新建的 scratch 图纸绘制。8 passed，但输出带 COM 忙碌异常诊断；如实记录，不能当作稳定性/性能结论。新增 `--cad-integration` 开关，默认测试不会启动 CAD。
- 最终离线 `pytest -q`：56 passed、33 skipped。真实 stdio tools/list 与固定 schema 一致；32 CAD 工具的 MCP 参数/返回样例测试为 fake CAD。真实 AutoCAD STA smoke + stdio MCP 创建查询：2 passed，均先新建专用空白图纸再写入并重读坐标/图层/半径；没有覆盖保存用户原图。
- 新增 Windows 离线 CI。本机 AutoCAD 文件版本 `25.1.60.0`、托管程序集 `25.1.60.0.0`，未安装 .NET SDK；插件/认证 Dispatcher/HTTP adapter/原子事务/性能 Benchmark 均待后续实施。没有发版或切换默认后端。

- 远端干净 Windows runner 的首轮测试步骤失败；Actions 日志下载域名从本机不可达，API 只能读到通用退出码。CI 增加失败时将 pytest 输出写入检查注释，保留原始非零退出码，便于直接定位 runner 差异。
- 通过 Actions 单 job 日志接口取得具体错误：无版本上限的 MCP 依赖在干净 runner 安装了 2.3.0，FastMCP 和测试 memory API 已变更；本机为 1.28.1。明确声明 `mcp[cli]>=1.28.1,<2`，保留已验证的 1.x 协议/API，避免把本轮变成 SDK 主版本迁移。
- 同步 conda environment.yml 中的 MCP/AnyIO 兼容范围，保证 conda 新建环境与 pyproject.toml 的 SDK 主版本一致。


## 2026-11-18（续）：安装 .NET SDK，完成 Bridge / HTTP 最小闭环

- 核对官方兼容表和本机 runtimeconfig，安装用户级 SDK 8.0.428，解压前验证官方 SHA-512；引用本机 SDK DLL，不在产物分发 Autodesk DLL。
- 实现原生 Kestrel loopback 认证服务、Idle 队列、managed-only 文档会话、线/圆/图层/查询、事务、revision 观察及有界十分钟去重；无任意脚本/命令端点。
- 实现 Python HTTPBackend、job DTO、URL 校验、配置选择器。未知写结果或轮询失败不重发、不回退；整数 ID 为文档会话别名，不混用 COM ObjectID。
- 自动化激活确有 e0434352；Windows 与 ODIS wrapper 有 ODISSDK.dll 访问异常/加载失败。曾据普通 dump 模块列表未列 Bridge 就断言未加载，证据不足，已纠正。用户确认普通桌面启动正常，验证改为 attach-only，不再隐式 Dispatch 启动。
- 清理之前测试遗留的临时实例，记录用户要求：开发结束关闭不用的自建 CAD 进程，保留用户实例。旧插件同步停服阻塞收尾，拆出后台停止/释放的 EmbeddedHttpHost，并覆盖无 UI 消息泵场景。
- 新 DLL 未签名确认阻塞 NETLOAD，用户手动“加载一次”后继续；右侧 CER 来自较早进程，未当作新 DLL 再次崩溃。最终加载与构建 DLL SHA-256 一致，构建零警告零错误。
- Python 离线 77 passed / 33 skipped；C# journal 11 项、host 三轮启停 12 项断言通过。实机验证七项工具、认证/Origin、去重/冲突、提交/回滚、revision、错误文档、切图绑定，以及真实 MCP stdio 和 Streamable HTTP 创建后重读。
- 最终报告 completed=true：四张测试图纸关闭、监听停止；用户授权重启的空白测试实例 PID 4940 最后已关闭，无 acad.exe 遗留。没有上传原始 dump、重置 CAD 配置或关闭安全策略。
- 增加安装脚本、配置样例、协议 schema、验收/事故记录、脱敏报告和无 CAD 的 .NET CI。批处理仍仅内部 Python API；全工具迁移、分页、长期故障测试及完整性能基准待完成，不发版、不切默认。

## 2026-11-18（续）：中英文 README 与项目视觉展示

- 重构英文 README，新增内容对应的简体中文版；首尾提供语言切换，整理能力表、快速开始、MCP 客户端配置、Web UI、后端选择、验证与文档导航。
- 新增原创 SVG 封面、约 1.2 MB 的 GIF 流程示意和 Mermaid 架构图。动画明确标注并非实机录屏，另附真实 Bridge 验证记录，不将示意图当作运行证据。
- 按实现说明 36 个注册工具、HTTP 支持的 7 项 CAD 工具、仅内部 API 的原子批处理，以及 MCP HTTP / CAD Bridge 的独立端口；保留默认 COM、HTTP 实验性与自动启动兼容性限制。
- 提供素材生成脚本与说明；Pillow 只用于文档素材制作，不增加项目运行依赖。检查两种语言的本地链接、锚点、JSON 配置与 SVG/GIF 完整性，并渲染检查首页排版。本轮不启动 AutoCAD，不改动已有 Web 与数据工作区修改。

## 2026-11-18（续）：README 改用真实 AutoCAD 操作画面

- 按用户建议重新尝试实机捕获。关闭其他页面后首次正确取得 CAD 画面；连续多次捕获触发工具的调用轮次限制，改为按工具步骤分段采集，没有把失败捕获或其他应用画面放进仓库。
- 正常启动专用 AutoCAD 实例，通过真实 MCP stdio / COM 完成 13 次工具调用，创建图层、100×60 安装板轮廓、中心孔、四个安装孔、标题和宽度标注；查询确认 8 个实体。使用预设参数脚本，未伪装为模型聊天。
- 将真实窗口快照整理为约 1.2 MB 的 10 步 GIF，替换双语 README 主演示。明确说明剪辑、缩短停顿与外置字幕；保留原示意 GIF 作为备用，不宣称连续实时录像、HTTP 执行或性能数据。
- 新增素材打包脚本和脱敏验证记录，保留源帧哈希、实际调用参数与返回几何。只裁掉任务栏、缩放、量化和添加画面外字幕，未生成或重绘 CAD 像素；原始快照保留本地。
- 所有自建临时图纸均已关闭且未保存，自建 CAD 进程已退出。早一轮清理因 COM 忙碌中断，后续确认只剩自己创建的空白图纸后恢复，最终无遗留 CAD 进程；保留原有 Web 与数据工作区修改。

## 2026-11-19：CAD-09 故障与双后端基准验证

- 新增显式启用的本机测试框架：原生故障矩阵、30 分钟/至少 1K 次混合调用、100/500/1000 实体的 COM/HTTP 逐条与 HTTP 批量对照；不扩展 MCP 工具、不改变默认 COM。
- 预先声明抽样、重任务减样、随机顺序、计时边界、几何归一化及资源停止预算。保存原始失败、预热与测量样本；小样本不计算 P95，批量成功路径比较不冒充 COM 原子事务。
- 每个基准样本使用相同 acadiso 模板的新测试图纸，并在计时外重建 Bridge，避免其 2048 条/十分钟 journal 上限污染逐条测试；队列/journal 饱和另作故障用例。
- 用户已打开的 CAD 实例和图纸保留，显式记录自建图纸并清理；用户手动选择插件“始终加载”。启动试跑发现 PyHANDLE 不支持上下文管理器及清理前不应无条件发送取消命令，修复测试框架并保留失败记录，未将其记成 CAD 通过或故障结果。
- 新增五项离线校验，验证几何证据、失败统计、小样本分位数与原始记录保护；均通过。真实稳定性与性能结果在后续条目记录。
- 补充清理原活动图纸与报告未完成状态的回归校验，离线累计 84 passed / 33 skipped；C# 11 项契约和 12 项 host 断言通过。独立 CAD 重启驱动仅用 HTTP 和新建实例，不与既有实例争抢 COM；提供操作员检查点，临时令牌不进入报告。
- 连续混合调用已实际运行 1800.625 秒，1793 次业务调用全部成功。原始收尾记录 completed=false 保留：Windows 短连接探测将超时误作监听未停止；后续 COM/TCP 独立核对确认只剩原有图纸且无 CAD 监听。改用 OS 监听表，不改写历史失败。
- 原生故障试跑已覆盖认证、回滚、去重、切图和响应丢失。交互 LINE 注入暴露同步命令阻塞及忙碌期间 COM 读取被拒绝，相关失败保留；新增独立 NativeTests 插件，以固定 5 秒主线程阻塞和命名事件提供可重复注入，不增加正式 HTTP 端点。该测试 DLL 构建零警告零错误，等待用户手动处理新的 NETLOAD 安全确认；剩余故障矩阵与性能测量尚未完成。
- 用户完成 NativeTests 加载后，定向四项忙碌用例通过；最新完整 fault-06-full 的 17 项原生用例全部通过，包括 64/6 队列饱和、2048 journal 上限、旧实例身份拒绝及端口冲突恢复。清理完成、原活动图纸恢复；CAD 进程重启将在额外的自建实例中独立验证，未记为已通过。
- 独立 restart-01 实际终止自建进程中的排队写入，确认 OUTCOME_UNKNOWN、仅一次 POST、旧客户端拒绝重绑定、旧 journal 丢失有明确语义、新客户端新文档创建圆并重读成功；两个自建 CAD 进程均关闭，用户原 PID 46240 保留。主矩阵原 not_run 不改写，渲染报告引用独立通过证据，合计 18 项故障通过。
- benchmark-01 保存 145 个测量和 51 个预热样本。HTTP 80/80 测量通过；COM 53/65 通过，12 个失败（7 com_error、4 AttributeError、1 KeyError）及 6 个预热失败全部保留。完整运行/清理完成不等于性能验收全过，benchmark.passed=false。1K 创建成功样本中位数：HTTP 批量 311.95 ms、HTTP 逐条 55835.85 ms、COM 8971.04 ms（COM 仅 3/5 成功）；不据有选择偏差的样本宣称普遍加速比。
- 提交全部失败尝试、连续调用、故障与性能原始 JSON/JSONL/CSV，新增可重生成的中文报告和 SVG 对照图。图表标注成功/失败数，小样本无 P95，检查图像无重叠；没有提交令牌、私有 DWG 或 dump。84 passed / 33 skipped，COM 默认配置未变；更大工具覆盖/分页属于下一阶段。

## 2026-11-19（续）：MCP 运行时工具与查询分页

- 新增 get_backend_status/get_job_status/execute_atomic_batch/query_entities_page 四项结构化工具，旧 36 项 schema 不变，总数 40。COM 状态只读工作线程元数据，不启动 CAD；其余不支持的能力明确报错，不回退。
- 新批处理与分页必须显式指定 document_id，避免依赖共享旧工具的活动绑定；批处理限制 1–200 步图层/线/圆，保留 request_id、revision 与完整 job 结果。查询 job 验证返回请求身份，未知写入仍不自动重放。
- 原生分页支持类型/图层过滤与字段裁剪，每页最多 1000，签名游标绑定实例、文档、查询与观察到的 revision，十分钟过期。仍逐页扫描模型空间，不宣称大型图纸查询优化；旧查询上限保留。
- 首轮离线验证 102 passed / 33 skipped，新增真实 MCP 参数/输出及 HTTP no-replay 测试；C# 游标篡改、跨实例/文档/查询、revision 与 TTL 共 11 项断言通过，原生 DLL 编译零警告零错误。实机新版 DLL 与超过 1000 项分页仍待验证，不据离线结果记为原生验收完成。
- 修复契约导出脚本的 worktree 来源：明确对子进程使用当前 checkout 的 src，避免 editable install 指向原仓库而错误地验证旧版本。同步双语 README、工具矩阵与调用/恢复文档，默认仍为 COM。
- 继续迁移矩形、重量级多段线、单行/多行文字、对齐标注，保持旧 MCP 参数与文字返回。新增几何重读字段；多段线遵循旧 COM 的 OCS XY/数据库 elevation 语义，文字沿用 MCP_CJK/SimSun，对齐标注暂限共同 WCS Z 平面。批处理白名单未扩展，编辑/图块属性/文件仍未迁移。
- 首轮新版实机 runtime-2026-11-19-01 通过 1205 个实体的 400/400/400/5 分页、唯一 ID、过滤/投影、去重与游标错误检查；随后矩形构造触发 db2dpoly.cpp@352 eInvalidInput，专用进程退出，原有 PID 46240 保留。客户端 OUTCOME_UNKNOWN，未重放；原失败 qualification 与 DLL 哈希保留，不记为全轮通过。
- 移除导致本次原生错误的多段线批量构造路径，改为默认父实体入库后在同一事务 AppendVertex，显式关闭顶点 wrapper 并最后设置 Closed。官方要求父对象必须先入库；具体原生内部根因未由 dump 确诊。修复构建零警告零错误，C# 游标 11 项断言通过，正在独立新实例复测。
- 修复版 runtime-02 五类几何创建/读取成功，脚本却把规范化后的标注线定义点 [10,5,0] 误判为不等于输入 [5,5,0]；独立只读重查确认同一条 y=5 标注线、测量 10。按端点/测量/线位置更正校验，原失败保留。
- runtime-03 的 43 次实际 MCP 调用全部符合预期（含预期错误），1205 项分页与五类绘图重读通过。收尾即时 PID 断言与异步退出竞争，原 qualification=false 保留；独立复核确认自建 PID 52600 已退出、原 PID 46240 保留，添加 cleanup-recovery 证据及有界退出等待回归。临时隔离令牌文件已删除，未替换原有实例锁定的已安装 DLL。
- 最终离线 103 passed / 33 skipped；C# journal 11、host 12、cursor 11 项断言通过。双语 README、迁移矩阵、复现脚本与报告同步真实范围，默认 COM 不变；编辑/图块属性/文件为后续工作，旧 CAD-09 性能数据不冒充新 DLL 性能。

## 2026-11-19（续）：README 精密工程风格封面

- 按用户要求重新设计静态封面，使用内置 image_gen 生成暖白/石墨/青绿的工程视觉：轴测装配体、正投影、剖面和尺寸标注体现 CAD，工具连接与空白接口表达 MCP 模块化和可扩展性。
- 新封面保存为 docs/assets/cover.png，中英文 README 共用图片并更新替代文字；旧 cover.svg 保留备用，原有真实演示 GIF 不变。归档实际生成提示词及概念图说明，不将生成插画当作实机画面或验收证据。
- 检查图片格式、文字与 README 展示；未修改业务代码、用户已有 Web 改动或 Cader 项目，本轮未操作 AutoCAD。

## 2026-11-19（续）：受控工作图、扩展事务与 DWG 保存件

- 仅修改 MCP：新增 create_working_drawing/get_working_drawing/save_working_drawing/reopen_saved_drawing 四项 HTTP 专用结构化工具，总数 44；原 36 项 schema 保持，COM 默认不变。新工作图绑定单位、输出目录和文档身份，不改旧工具绑定；请求预分配 ID，提交前原生实例校验，结果未知不自动重放。
- 保存为新 DWG 副本，保留编辑器文档名；临时完整保存后不覆盖发布，记录 SHA-256/字节数/源 revision。保存件只凭本实例 artifact_id 校验哈希并只读重开，返回独立 document_id；文件操作不进入图元事务，不声称文件失败已回滚。记录为内存态，重启不可恢复，最多 2048 项；路径/已有文件/链接边界明确拒绝。
- 原子批处理扩至图层、线、圆、圆弧、矩形、多段线、单行/多行文字、对齐标注九项；保留 OCS XY、角度与标注平面兼容规则。分页补圆弧、法向、bulge、线型/颜色/线宽及图层属性，并标记不支持的几何。
- 离线 125 passed / 33 skipped；C# Journal 11、Host 12、Cursor 11、Artifact 17 项断言；插件构建零警告零错误。新增 artifact 路径/不覆盖测试并接入 Windows CI，保留旧 runtime v0.1 schema 快照，新 v0.2 独立导出。
- 自建 AutoCAD PID 57436，用户手动加载插件后，真实 stdio MCP→HTTP→CAD 的 42 次调用全部符合预期（11 项预期错误）：混合事务首/中/末失败无实体/图层/样式残留，八类实体重读、保存哈希、只读重开独立查询、源图后续修改隔离、覆盖/过期 revision/错误实例/越界/篡改/只读写入拒绝均通过。公开脱敏调用日志和指纹；无私有原图或 DWG 二进制。
- 所有三张自建图纸关闭后 COM Quit 属性不可用；保留收尾异常，观察空开始页后 Alt+F4 正常退出，独立确认无剩余 acad 进程。未修改 Cader 或已有用户 Web/数据改动；本轮不是图片重绘、长期稳定性或性能验收。

## 2026-11-19（续）：Cader 公共契约对齐审阅

- 只读审阅 Cader be2887f 的 managed-cad-v1 文档、schema 和程序客户端，不将文档内容视为 MCP 已实现能力或用户授权。新增 MCP 侧对齐意见：列明名称/DTO/单位/文字点位/alias/能力/文件字段映射，以及只读重开 managed 含义、rollback revision、输出授权时点和重开对账身份等必须冻结的语义。
- 新增只读结构诊断脚本；实际 stdio tools/list 与默认状态显示 44 工具、COM 后端，Cader 所需三个工具名缺失。既有合成 HTTP 实机记录的六类返回均不直接满足 Cader 当前 schema；公开报告明确区分本轮只读调用与历史结构样本，不声称 DWG 联合验收。
- 增加不含凭据的独立 HTTP 配置示例，解释 stdio MCP 与 HTTP CAD 后端的区别；不修改默认 COM、Cader 文件、原有业务接口或插件。适配 profile 尚未实现，待双方冻结语义后再做代码与实机验收。

## 2026-11-19（续）：确认 Cader 契约修订 2 实施基线

- 审阅 Cader 266c689 的回应，接受 Working/Verification Binding、observed_database_events、create 显式 output_directory、按操作对账和交集 ID 字符集；新图不要求初始 revision 为 0。此为 MCP 实施基线确认，不宣称双方发布已冻结或专用 profile 已实现。
- 原字节保存共享 schema/examples/manifest，校验 SHA-256 分别 e239266e…dd28 / 9e33ab75…0e41，保留源 unfrozen 状态；快照禁用 Git 文本换行转换。新增独立 MCP 确认记录和确定性 DTO→原生映射约定，不改变既有 Journal.Canonical/hash 规则，不把审计 hash 当重放授权。
- 新增离线共享向量验证：18 结构、11 操作身份、1 精确审计字符串，共 30 项通过；包含固定 manifest 与篡改拒绝的 32 项 pytest 通过。该结果不代替适配器、HTTP 或 DWG 实机验收；未修改 Cader、默认 COM、旧 44 接口或插件，也未启动 CAD/模型。

## 2026-11-19（续）：版本化 Cader profile 与真实 DWG 联合闭环

- 实现独立 `python -m autocad_mcp.managed_server` stdio 入口，七项工具按共享 cader-cad/1 修订 2 schema 校验及转换，直接返回公共 DTO；普通入口仍 44 工具、默认 COM 不变。运行时打包同一份精确 schema，并声明 jsonschema 依赖。
- 原生 journal 新增紧凑 request records，接受时固定 profile/operation/输入文档/预期 revision/源 artifact，完成压缩后保留；既有去重 hash 与旧 job 回包不变。失败在 CAD 线程完成事务展开后观察权威 revision，拿不到时不伪造；写入锁文档后检查 revision，Python 重启可按现存原生记录对账，不自动重放未知写入。
- profile 首轮仅图层 0 的 line/circle/text，检查规范样式并显式标记无法完整表达的属性。显式绑定规范本地 .cader/artifacts，保存禁止覆盖，重开生成独立只读验收图；文件操作与实体事务分开。
- 离线 178 passed / 33 skipped；C# Journal 17 / Host 12 / Cursor 11 / Artifact 17 共 57 断言通过；插件 Release 零警告零错误，wheel 验证入口、配置与 schema 原字节。
- Cader 266c689 实际 CLI 两轮均 exit 0、verification passed：状态→创建→空图查询→三实体事务→源查询→保存→只读重开→独立查询。两轮额外原生回滚均 revision 0→6、无实体/图层/样式残留；新 Python adapter 读回相同权威失败身份。逐文件核对 Cader 128 个 tracked 文件未改，不修改其代码/策略/默认配置。
- 使用自建 AutoCAD PID 33564，结束关闭全部测试图纸与进程；首次快速关闭的 RPC_E_CALL_REJECTED 保留并有界恢复，最终无 acad 进程。公开脱敏两轮证据、源指纹、请求原文摘要核对及复现脚本；不提交 token 或 DWG。通过范围为固定计划真实文件闭环，不冒充图片识别、复杂电路重绘、性能或长期稳定性验收，也不代替双方发布冻结。

## 2026-11-21：Cader 用户日志中的图层依赖与延迟截图

- 来源：用户明确要求修复Cader 17:24 draw_polyline(HOUSE)部分执行与反复屏障，关联codesknight/Cader#20 REQ-032。未预建图层时旧实现先AddPolyline再赋层，错误后留下0层实体；本轮在9类创建入口先查图层存在/可写，属性失败只清理本次新增实体（含hatch边界），不全局Undo。清理失败明确保留原错误和cleanup_errors；不是事务或可重放证明。
- 实机第一轮模型确认16写入后，export_current_view超时，PNG延迟到达。改为BACKGROUNDPLOT=0前台打印、检查布尔回执、显式extents/fit/upright，PlotConfiguration.CopyFrom快照完整恢复，finally逐项恢复系统变量/QuietErrorMode并删除临时配置；拒绝覆盖已有文件。原生未知仍由Cader保留屏障，不用重打伪造成功。
- 离线新增38例创建安全与5例导出恢复。前一全量216 passed/33 skipped；加入导出后的最终全量/CI另记。初次fixture遗漏InsertBlock已修正；误在Cader目录用此环境pytest导致导入失败是检查目录问题。项目未配置ruff，借用Cader环境isolated I/F检查；不把Cader严格BLE规则对旧代码的报告视为本仓库既有检查通过。
- 独立真实AutoCAD新图：缺图层后实体0；建层后多段线正常；后续故意赋无效图层只清理第二个新增实体，已有测试实体保留。新图PNG约1.110秒完成，前后BACKGROUNDPLOT=2、空设备名/scale/rotation/临时配置数量均恢复；仅关闭本次新图。真实模型完整质量另由Cader记录，首轮export失败保留。
- 既有web/backend、资料和tests/images改动保持原样，不混入本次提交。此修复不覆盖进程崩溃/丢回执的权威终态，也未宣称任意图纸视觉质量或像素映射已解决。

- 最终本地221 passed/33 skipped；实现538db9c已普通推送codex/dependency-preflight，[CI 44891530548](https://github.com/codesknight/AutoCAD-MCP/actions/runs/44891530548) offline与bridge-contracts均成功。Cader第二轮真实房子/树18确认、unknown0、两次有效自动视觉及一轮修正，无写屏障；完整质量仍因计划原生类型/需求语义和截图边缘pending，不能据此宣称任意输出质量通过。本轮新图经完整快照与未命名状态核对后关闭，用户Drawing1/2保留。Cader完整分层证据在其docs/validation/2026-11-21-dependency-and-partial-execution.md，最终文档CI在Cader#20同步。

## 2026-11-21（续）：手稿重绘视觉捕获边距

- 关联Cader#20 REQ-034；原extents fit图形可能触边，后处理补白不能证明原图完整。本轮Regen后读取EXTMIN/MAX，验证有限值及顺序，投影八角到DCS，用5%原生窗口边距设置acWindow再fit-to-page；空模型/纸空间保留原extents路径。保持完整打印快照恢复，不修改图元或回放未知操作。
- 真实AutoCAD仅新建本次测试图：PNG约1.188秒，导出设置前后完全相同，边缘前景像素0/possible_clipping=false；核对后关闭该测试图，既有用户图未修改。私有证据由Cader `.cader/runs/dependency-native-23923545-6703-44df-8d5f-dce6b6aa15b0` 保存，不提交图纸。
- 实际全量pytest 221 passed/33 skipped；isolated ruff I/F改动两文件通过。新增窗口投影/边距/恢复断言属于fixture，另有上述实机，不当成完整模型重绘验收。后者仍由Cader分层报告。原始失败保留，web/backend/训练资料的既有改动保持不动。
