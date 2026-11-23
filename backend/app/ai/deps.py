from fastapi import HTTPException

from app.ai.openai_provider import create_openai_chat_provider, create_openai_embedding_provider
from app.ai.providers import ChatProvider, EmbeddingProvider
from app.config import get_settings


def get_chat_provider() -> ChatProvider:
    api_key = get_settings().openai_api_key
    if not api_key:
        raise HTTPException(status_code=503, detail="AI_NOT_CONFIGURED")
    return create_openai_chat_provider(api_key)


def get_embedding_provider() -> EmbeddingProvider:
    api_key = get_settings().openai_api_key
    if not api_key:
        raise HTTPException(status_code=503, detail="AI_NOT_CONFIGURED")
    return create_openai_embedding_provider(api_key)
