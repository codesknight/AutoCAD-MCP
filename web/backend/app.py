from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from web.backend import conversation_store
from web.backend.agent_loop import run_turn

app = FastAPI(title="AutoCAD MCP Web UI")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


class ChatRequest(BaseModel):
    conversation_id: str
    provider: str  # "anthropic" | "openai" | "openai_compatible" | "doubao"
    api_key: str = ""  # optional for local deployments that don't check auth
    base_url: str | None = None
    model: str | None = None
    message: str
    image_base64: str | None = None  # raw base64 payload, no "data:...;base64," prefix
    image_media_type: str | None = None  # e.g. "image/png"


class ChatResponse(BaseModel):
    reply: str


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    messages = conversation_store.get(req.conversation_id)
    # api_key and the image payload are used for this call only -- never
    # logged, persisted, or stored beyond conversation_store's message history.
    try:
        reply = await run_turn(
            messages,
            req.provider,
            req.api_key,
            req.message,
            req.base_url,
            req.model,
            req.image_base64,
            req.image_media_type,
        )
    except Exception as exc:  # noqa: BLE001 - surface any provider/network error to the chat UI
        exc_text = str(exc)
        if "image_url" in exc_text and req.image_base64:
            return ChatResponse(
                reply="出错了：当前选的模型不支持图片输入（vision），换一个支持看图的模型再试。"
                f"\n原始报错：{exc_text}"
            )
        return ChatResponse(reply=f"出错了：{exc_text}")
    return ChatResponse(reply=reply)


@app.post("/api/reset")
async def reset(conversation_id: str) -> dict:
    conversation_store.reset(conversation_id)
    return {"ok": True}


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
