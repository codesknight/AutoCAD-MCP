from web.backend import mcp_client
from web.backend.providers.anthropic_provider import AnthropicProvider, to_anthropic_tools
from web.backend.providers.openai_provider import OpenAIProvider, to_openai_tools

MAX_TOOL_ITERATIONS = 8


def _build_provider(provider: str):
    if provider == "anthropic":
        return AnthropicProvider(), to_anthropic_tools
    if provider in ("openai", "openai_compatible"):
        return OpenAIProvider(), to_openai_tools
    raise ValueError(f"unknown provider: {provider}")


async def run_turn(
    messages: list[dict],
    provider: str,
    api_key: str,
    base_url: str | None = None,
) -> str:
    """Send the user's latest message (already appended to `messages` by the
    caller) through the LLM, executing any AutoCAD MCP tool calls it makes
    via the real MCP protocol, until it produces a final text reply."""
    llm, to_provider_tools = _build_provider(provider)
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
