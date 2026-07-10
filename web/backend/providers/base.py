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
