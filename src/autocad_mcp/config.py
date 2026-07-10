import json
from pathlib import Path
from pydantic import BaseModel

_CONFIG_PATH = Path(__file__).parent / "config.json"


class Config(BaseModel):
    cad_type: str
    prog_id: str
    prog_id_fallbacks: list[str] = []
    connect_timeout: int = 15
    visible: bool = True


def load_config(path: Path = _CONFIG_PATH) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Config(**data)
