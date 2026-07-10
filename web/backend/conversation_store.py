"""In-memory conversation history, keyed by conversation_id.

Not persisted to disk and not shared across processes -- fine for a local,
single-user demo; a real deployment would need a proper session store.
"""
_conversations: dict[str, list[dict]] = {}


def get(conversation_id: str) -> list[dict]:
    return _conversations.setdefault(conversation_id, [])


def reset(conversation_id: str) -> None:
    _conversations.pop(conversation_id, None)
