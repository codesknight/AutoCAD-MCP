from dataclasses import dataclass


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ProviderResult:
    text: str | None
    tool_calls: list[ToolCall]


class LLMProvider:
    """One LLMProvider instance handles one turn of a conversation: send the
    running message history + available tools, get back either a final text
    reply or a batch of tool calls to execute."""

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        api_key: str,
        base_url: str | None = None,
    ) -> ProviderResult:
        raise NotImplementedError

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        api_key: str,
        base_url: str | None = None,
    ):
        """流式版本的 chat()。逐步 yield {"type": "text_delta", "text": ...}，
        正常结束时 yield 一次 {"type": "done", "tool_calls": [...]}（把最终的
        assistant 消息追加进 messages，和 chat() 的副作用保持一致）。

        出错时必须 yield {"type": "error", "message": str(exc)} 然后 return，
        绝不能把异常 raise 出这个生成器——Starlette 的 StreamingResponse 消费
        异步生成器时，只要生成器"某次 yield 之后、同一帧内又抛了异常"就会报
        `RuntimeError: Attempted to exit a cancel scope that isn't the current
        tasks's current cancel scope`（实测确认过和具体用的 SDK 无关，是这类
        异步生成器链路本身的限制）。
        """
        raise NotImplementedError
        yield  # pragma: no cover -- makes this an async generator, never reached

    def format_tool_result(self, tool_call: ToolCall, result_text: str) -> dict:
        """Build the provider-specific message representing a tool's output,
        to append to the running message history before the next chat() call."""
        raise NotImplementedError

    def build_user_message(
        self, text: str, image_base64: str | None = None, image_media_type: str | None = None
    ) -> dict:
        """Build the provider-specific user message, optionally with an image
        (vision input) alongside the text."""
        raise NotImplementedError
