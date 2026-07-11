"""豆包 (Doubao) via the native Volcengine Ark runtime SDK.

Ark's chat.completions.create() mirrors the OpenAI SDK's request/response
shapes (ChatCompletionMessage, tool_calls, image_url content parts are all
the same fields) -- confirmed against the volcenginesdkarkruntime source
(https://github.com/volcengine/volcengine-python-sdk/tree/master/volcenginesdkarkruntime).
So only the client construction differs from OpenAIProvider; everything
else (tool-call parsing, format_tool_result, build_user_message) is reused
via subclassing rather than duplicated.
"""
from volcenginesdkarkruntime import AsyncArk

from web.backend.providers.openai_provider import OpenAIProvider, _normalize_base_url

DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"


class DoubaoProvider(OpenAIProvider):
    """`model` must be an Ark inference endpoint ID (e.g. `ep-xxxxxxxx-xxxxx`)
    created on the 火山方舟 console, or a directly-callable model name."""

    def _build_client(self, api_key: str, base_url: str | None):
        return AsyncArk(api_key=api_key, base_url=_normalize_base_url(base_url) or DEFAULT_BASE_URL)
