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
