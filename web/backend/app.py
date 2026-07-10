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
    provider: str  # "anthropic" | "openai" | "openai_compatible"
    api_key: str
    base_url: str | None = None
    message: str


class ChatResponse(BaseModel):
    reply: str


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    messages = conversation_store.get(req.conversation_id)
    messages.append({"role": "user", "content": req.message})
    # api_key is used for this call only -- never logged, persisted, or
    # stored in conversation_store.
    try:
        reply = await run_turn(messages, req.provider, req.api_key, req.base_url)
    except Exception as exc:  # noqa: BLE001 - surface any provider/network error to the chat UI
        return ChatResponse(reply=f"出错了：{exc}")
    return ChatResponse(reply=reply)


@app.post("/api/reset")
async def reset(conversation_id: str) -> dict:
    conversation_store.reset(conversation_id)
    return {"ok": True}


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
