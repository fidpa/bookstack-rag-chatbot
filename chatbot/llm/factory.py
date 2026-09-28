"""LLM provider selection: Azure OpenAI first, Ollama as an opt-in fallback."""

import logging
import os
import threading
from typing import Optional

from .base import LLMProvider
from .models import DEFAULT_MODELS
from .providers.azure import AzureProvider
from .providers.ollama import OllamaProvider

logger = logging.getLogger(__name__)

# Ollama must be switched on explicitly: an unintended local fallback would
# answer from a much weaker model without anyone noticing.
ENABLE_OLLAMA = os.getenv("ENABLE_OLLAMA_FALLBACK", "false").lower() == "true"

_providers: dict = {}
_lock = threading.Lock()


def _provider(name: str) -> LLMProvider:
    """One instance per provider and process, so HTTP connections are reused."""
    with _lock:
        if name not in _providers:
            if name == "azure":
                _providers[name] = AzureProvider()
            else:
                _providers[name] = OllamaProvider(
                    model_name=os.getenv("OLLAMA_MODEL") or DEFAULT_MODELS["ollama"],
                    base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
                )
        return _providers[name]


def get_llm_provider() -> Optional[LLMProvider]:
    """
    The provider that should answer the next request.

    Returns:
        Azure if its credentials are configured, otherwise Ollama if
        ENABLE_OLLAMA_FALLBACK is true and the model is pulled, otherwise None.
    """
    azure = _provider("azure")
    if azure.is_available():
        return azure

    if not ENABLE_OLLAMA:
        logger.error("Azure OpenAI not configured and Ollama fallback is disabled")
        return None

    ollama = _provider("ollama")
    if ollama.is_available():
        return ollama

    logger.error("No LLM provider available (Azure not configured, Ollama unreachable)")
    return None
