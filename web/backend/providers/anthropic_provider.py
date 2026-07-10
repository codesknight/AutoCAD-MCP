import anthropic
from mcp.types import Tool as MCPTool

from web.backend.providers.base import LLMProvider, ProviderResult, ToolCall

DEFAULT_MODEL = "claude-opus-4-8"


def to_anthropic_tools(mcp_tools: list[MCPTool]) -> list[dict]:
    return [
        {"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
        for t in mcp_tools
    ]


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        api_key: str,
        base_url: str | None = None,
    ) -> ProviderResult:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=self.model,
            max_tokens=4096,
            tools=tools,
            messages=messages,
        )

        text = next((b.text for b in response.content if b.type == "text"), None)
        tool_calls = [
            ToolCall(id=b.id, name=b.name, input=b.input)
            for b in response.content
            if b.type == "tool_use"
        ]

        # Anthropic requires the full assistant content (including tool_use
        # blocks) appended back verbatim before the next turn's tool_result.
        messages.append({"role": "assistant", "content": response.content})

        return ProviderResult(text=text, tool_calls=tool_calls)

    def format_tool_result(self, tool_call: ToolCall, result_text: str) -> dict:
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_call.id, "content": result_text}
            ],
        }
