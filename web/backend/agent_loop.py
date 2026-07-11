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
