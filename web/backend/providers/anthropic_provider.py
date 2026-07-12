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
        async with anthropic.AsyncAnthropic(api_key=api_key) as client:
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

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        api_key: str,
        base_url: str | None = None,
    ):
        error: Exception | None = None
        final_message = None
        # client 显式用 `async with` 关掉，不留给垃圾回收器兜底。
        # 出错时在这里直接 yield 一个 error 事件、不再 raise：实测过，一个异步
        # 生成器只要"某次 yield 之后，同一帧内后面又抛了异常"，被 Starlette
        # StreamingResponse 消费时就会报 `RuntimeError: Attempted to exit a
        # cancel scope that isn't the current tasks's current cancel scope`——
        # 用最小化对照测试确认过这跟 httpx/Anthropic SDK 无关，是这类异步生成器
        # 链路本身的限制，只要把错误转成普通 yield 出去的值、绝不 raise，就不会
        # 触发。
        async with anthropic.AsyncAnthropic(api_key=api_key) as client:
            # 注意：`client.messages.stream(...)` 这个 `async with` 语句本身的
            # `__aenter__`（不是它的 body）就可能抛异常——比如 API Key 无效时，
            # 认证校验是在建立请求连接的时候做的，报错发生在进入这个 with 块之前。
            # 所以 try 必须整个包住这条 `async with` 语句（entry+body+exit），
            # 只在 body 内部包 try 是不够的，实测验证过这个具体的失败路径。
            try:
                async with client.messages.stream(
                    model=self.model,
                    max_tokens=4096,
                    tools=tools,
                    messages=messages,
                ) as stream:
                    async for text in stream.text_stream:
                        yield {"type": "text_delta", "text": text}
                    final_message = await stream.get_final_message()
            except Exception as exc:  # noqa: BLE001
                error = exc

        if error is not None:
            yield {"type": "error", "message": str(error)}
            return

        tool_calls = [
            ToolCall(id=b.id, name=b.name, input=b.input)
            for b in final_message.content
            if b.type == "tool_use"
        ]
        messages.append({"role": "assistant", "content": final_message.content})
        yield {"type": "done", "tool_calls": tool_calls}

    def format_tool_result(self, tool_call: ToolCall, result_text: str) -> dict:
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_call.id, "content": result_text}
            ],
        }

    def build_user_message(
        self, text: str, image_base64: str | None = None, image_media_type: str | None = None
    ) -> dict:
        if not image_base64:
            return {"role": "user", "content": text}
        return {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image_media_type or "image/png",
                        "data": image_base64,
                    },
                },
                {"type": "text", "text": text},
            ],
        }
