import json

import openai
from mcp.types import Tool as MCPTool

from web.backend.providers.base import LLMProvider, ProviderResult, ToolCall

DEFAULT_MODEL = "gpt-4o"


def to_openai_tools(mcp_tools: list[MCPTool]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.inputSchema,
            },
        }
        for t in mcp_tools
    ]


class OpenAIProvider(LLMProvider):
    """Handles both real OpenAI (base_url=None) and OpenAI-compatible
    endpoints (Qwen/DeepSeek/GLM/...) via an explicit base_url."""

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        api_key: str,
        base_url: str | None = None,
    ) -> ProviderResult:
        client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        response = await client.chat.completions.create(
            model=self.model,
            tools=tools,
            messages=messages,
        )
        message = response.choices[0].message

        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, input=json.loads(tc.function.arguments))
            for tc in (message.tool_calls or [])
        ]

        messages.append(
            {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in (message.tool_calls or [])
                ]
                or None,
            }
        )

        return ProviderResult(text=message.content, tool_calls=tool_calls)

    def format_tool_result(self, tool_call: ToolCall, result_text: str) -> dict:
        return {"role": "tool", "tool_call_id": tool_call.id, "content": result_text}

    def build_user_message(
        self, text: str, image_base64: str | None = None, image_media_type: str | None = None
    ) -> dict:
        if not image_base64:
            return {"role": "user", "content": text}
        data_url = f"data:{image_media_type or 'image/png'};base64,{image_base64}"
        return {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": text},
            ],
        }
