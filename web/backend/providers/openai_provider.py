import json

import openai
from mcp.types import Tool as MCPTool

from web.backend.providers.base import LLMProvider, ProviderResult, ToolCall

DEFAULT_MODEL = "gpt-4o"


def _normalize_base_url(base_url: str | None) -> str | None:
    """The openai SDK appends '/chat/completions' itself -- base_url must be
    the API root (e.g. 'https://open.bigmodel.cn/api/paas/v4/'), not the full
    endpoint. Strip a trailing '/chat/completions' if the user pasted the
    full endpoint URL by mistake, to avoid a doubled path -> 404."""
    if not base_url:
        return base_url
    stripped = base_url.rstrip("/")
    if stripped.endswith("/chat/completions"):
        stripped = stripped[: -len("/chat/completions")]
    return stripped


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

    def _build_client(self, api_key: str, base_url: str | None):
        # Locally-deployed servers (openai_compatible pointed at localhost)
        # commonly don't check the Authorization header at all -- the SDK
        # itself refuses to construct a client with an empty key, so fall
        # back to a placeholder that satisfies the SDK but is never a real
        # credential.
        return openai.AsyncOpenAI(api_key=api_key or "not-needed", base_url=_normalize_base_url(base_url))

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        api_key: str,
        base_url: str | None = None,
    ) -> ProviderResult:
        # 显式 async with 关闭底层 httpx client——不关的话交给垃圾回收器兜底，
        # 见 anthropic_provider.py 里那次实测复现的 StreamingResponse + anyio
        # cancel scope 报错，同一类问题，这里一并修掉。
        async with self._build_client(api_key, base_url) as client:
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

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        api_key: str,
        base_url: str | None = None,
    ):
        content_parts = []
        # index -> {"id", "name", "arguments"} -- tool call fragments arrive
        # split across chunks (arguments especially, one piece at a time) and
        # are matched up by their position in the response, not by id.
        tool_call_acc: dict[int, dict] = {}
        error: Exception | None = None

        # 出错时在这里直接 yield 一个 error 事件、不再 raise——原因见
        # anthropic_provider.py::chat_stream 里那段注释（实测确认过的
        # Starlette StreamingResponse + 异步生成器的限制，和 SDK 无关）。
        async with self._build_client(api_key, base_url) as client:
            try:
                stream = await client.chat.completions.create(
                    model=self.model,
                    tools=tools,
                    messages=messages,
                    stream=True,
                )
                async for chunk in stream:
                    if not chunk.choices:
                        continue  # some OpenAI-compatible servers send a trailing usage-only chunk
                    delta = chunk.choices[0].delta
                    if delta.content:
                        content_parts.append(delta.content)
                        yield {"type": "text_delta", "text": delta.content}
                    for tc_delta in delta.tool_calls or []:
                        entry = tool_call_acc.setdefault(tc_delta.index, {"id": None, "name": None, "arguments": ""})
                        if tc_delta.id:
                            entry["id"] = tc_delta.id
                        if tc_delta.function and tc_delta.function.name:
                            entry["name"] = tc_delta.function.name
                        if tc_delta.function and tc_delta.function.arguments:
                            entry["arguments"] += tc_delta.function.arguments
            except Exception as exc:  # noqa: BLE001
                error = exc

        if error is not None:
            yield {"type": "error", "message": str(error)}
            return

        content = "".join(content_parts) or None
        ordered = [tool_call_acc[i] for i in sorted(tool_call_acc)]
        tool_calls = [
            ToolCall(id=entry["id"], name=entry["name"], input=json.loads(entry["arguments"] or "{}"))
            for entry in ordered
        ]

        messages.append(
            {
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": entry["id"],
                        "type": "function",
                        "function": {"name": entry["name"], "arguments": entry["arguments"]},
                    }
                    for entry in ordered
                ]
                or None,
            }
        )
        yield {"type": "done", "tool_calls": tool_calls}

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
