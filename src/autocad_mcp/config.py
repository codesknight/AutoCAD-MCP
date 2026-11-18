import json
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, Field, field_validator

_CONFIG_PATH = Path(__file__).parent / "config.json"


class HTTPConfig(BaseModel):
    base_url: str = "http://127.0.0.1:8765"
    connect_timeout_seconds: float = Field(default=3, gt=0, le=30)
    request_timeout_seconds: float = Field(default=30, gt=0, le=300)
    token_env: str = "AUTOCAD_BRIDGE_TOKEN"

    @field_validator("base_url")
    @classmethod
    def loopback_only(cls, value):
        url = urlsplit(value)
        if url.scheme != "http" or url.hostname != "127.0.0.1" or url.username or url.password or url.path not in ("", "/") or url.query or url.fragment:
            raise ValueError("Bridge URL must be plain HTTP on 127.0.0.1 with no credentials, path or query")
        if not url.port or not 1024 <= url.port <= 65535:
            raise ValueError("Bridge requires an explicit port between 1024 and 65535")
        return value.rstrip("/")


class Config(BaseModel):
    backend: Literal["com", "http"] = "com"
    http: HTTPConfig = Field(default_factory=HTTPConfig)
    cad_type: str
    prog_id: str
    prog_id_fallbacks: list[str] = []
    connect_timeout: int = 15
    visible: bool = True


def load_config(path: Path | None = None) -> Config:
    path = path or Path(os.environ.get("AUTOCAD_MCP_CONFIG", str(_CONFIG_PATH)))
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Config(**data)
