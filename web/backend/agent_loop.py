from web.backend import mcp_client
from web.backend.providers.anthropic_provider import AnthropicProvider, to_anthropic_tools
from web.backend.providers.doubao_provider import DoubaoProvider
from web.backend.providers.openai_provider import OpenAIProvider, to_openai_tools

MAX_TOOL_ITERATIONS = 8

# Providers with no sane default model (an arbitrary compatible endpoint, or
# an Ark inference endpoint ID) -- the user must supply one.
MODEL_REQUIRED_PROVIDERS = ("openai_compatible", "doubao")


def _build_provider(provider: str, model: str | None):
    if provider == "anthropic":
        return (AnthropicProvider(model) if model else AnthropicProvider()), to_anthropic_tools
    if provider in ("openai", "openai_compatible"):
        return (OpenAIProvider(model) if model else OpenAIProvider()), to_openai_tools
    if provider == "doubao":
        return DoubaoProvider(model), to_openai_tools
    raise ValueError(f"unknown provider: {provider}")


async def run_turn(
    messages: list[dict],
    provider: str,
    api_key: str,
    message: str,
    base_url: str | None = None,
    model: str | None = None,
    image_base64: str | None = None,
    image_media_type: str | None = None,
) -> str:
    """Build and append the user's latest turn (text, optionally with an
    image for vision input), then run it through the LLM, executing any
    AutoCAD MCP tool calls it makes via the real MCP protocol, until it
    produces a final text reply."""
    if provider in MODEL_REQUIRED_PROVIDERS and not model:
        return "使用 OpenAI 兼容 / 豆包模式时必须填写模型名称（豆包填推理接入点 ID，比如 ep-xxxxxxxx-xxxxx）"

    llm, to_provider_tools = _build_provider(provider, model)
    messages.append(llm.build_user_message(message, image_base64, image_media_type))

    mcp_tools = await mcp_client.list_tools()
    provider_tools = to_provider_tools(mcp_tools)

    for _ in range(MAX_TOOL_ITERATIONS):
        result = await llm.chat(messages, provider_tools, api_key, base_url)
        if not result.tool_calls:
            return result.text or ""

        for tool_call in result.tool_calls:
            result_text = await mcp_client.call_tool(tool_call.name, tool_call.input)
            messages.append(llm.format_tool_result(tool_call, result_text))

    return "(达到最大工具调用轮数，已停止)"


async def run_turn_stream(
    messages: list[dict],
    provider: str,
    api_key: str,
    message: str,
    base_url: str | None = None,
    model: str | None = None,
    image_base64: str | None = None,
    image_media_type: str | None = None,
):
    """流式版本的 run_turn：逐步 yield 结构化事件而不是等全部跑完才返回一个字符串。
    事件类型：
    - {"type": "text_delta", "text"}：大模型输出的文字片段，实时转发。
    - {"type": "tool_call", "name", "input"}：即将执行某个工具调用。
    - {"type": "tool_result", "name", "result"}：工具调用的结果。
    - {"type": "error", "message"}：出错了（提前结束）。
    - {"type": "done"}：这一轮彻底结束（正常结束或达到最大轮数）。
    这样网页前端可以在等待工具执行（尤其是慢工具，比如 VQA）的过程中，看到具体在
    执行哪个工具，而不是只有一个"思考中..."的计时器（参见 devlog 里 VQA "卡住"排查
    那次发现的可观测性缺口）。

    实测发现一个反直觉的坑：这里每一处"try 一个可能失败的调用、失败了就 yield 一个
    error 事件"都必须各自独立、紧贴着那次调用本身写，不能用一个大 try/except 把
    "中间还有别的 yield" 的一大段逻辑整个包起来。原因是 Starlette 的
    StreamingResponse 配合 anyio 有个已验证的问题：只要一个异步生成器里，"某次
    yield 之后、同一个生成器帧内后面又抛了异常"，不管这个异常是从哪里来的（哪怕是
    一个完全无关、什么都不做的 `async with`/`try...finally`），最后都会在
    Starlette 收尾时报 `RuntimeError: Attempted to exit a cancel scope that
    isn't the current tasks's current cancel scope`——用最小化的对照测试复现过，
    和 Anthropic SDK/httpx 都没关系，是这一整套异步生成器链路本身的限制。规避方法
    就是这里这样写：每个可能失败的调用单独包一层 try/except，失败就立刻
    `yield` 错误事件 + `return`，绝不允许异常真的从任何 yield 过的生成器帧里
    "跨帧传播"。
    """
    if provider in MODEL_REQUIRED_PROVIDERS and not model:
        yield {
            "type": "text_delta",
            "text": "使用 OpenAI 兼容 / 豆包模式时必须填写模型名称（豆包填推理接入点 ID，比如 ep-xxxxxxxx-xxxxx）",
        }
        yield {"type": "done"}
        return

    try:
        llm, to_provider_tools = _build_provider(provider, model)
    except Exception as exc:  # noqa: BLE001
        yield {"type": "error", "message": str(exc)}
        yield {"type": "done"}
        return

    messages.append(llm.build_user_message(message, image_base64, image_media_type))

    try:
        mcp_tools = await mcp_client.list_tools()
    except Exception as exc:  # noqa: BLE001
        yield {"type": "error", "message": str(exc)}
        yield {"type": "done"}
        return
    provider_tools = to_provider_tools(mcp_tools)

    for _ in range(MAX_TOOL_ITERATIONS):
        tool_calls = []
        async for event in llm.chat_stream(messages, provider_tools, api_key, base_url):
            if event["type"] == "text_delta":
                yield event
            elif event["type"] == "error":
                yield event
                yield {"type": "done"}
                return
            elif event["type"] == "done":
                tool_calls = event["tool_calls"]

        if not tool_calls:
            yield {"type": "done"}
            return

        for tool_call in tool_calls:
            yield {"type": "tool_call", "name": tool_call.name, "input": tool_call.input}
            try:
                result_text = await mcp_client.call_tool(tool_call.name, tool_call.input)
            except Exception as exc:  # noqa: BLE001
                yield {"type": "error", "message": str(exc)}
                yield {"type": "done"}
                return
            yield {"type": "tool_result", "name": tool_call.name, "result": result_text}
            messages.append(llm.format_tool_result(tool_call, result_text))

    yield {"type": "text_delta", "text": "(达到最大工具调用轮数，已停止)"}
    yield {"type": "done"}
