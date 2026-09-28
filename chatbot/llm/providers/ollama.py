"""Ollama provider — local LLM integration over the Ollama HTTP API."""

import logging
import requests
from typing import Any, Dict, List
from ..base import LLMError, LLMProvider
from ..models import DEFAULT_MODELS
from ..utils import format_messages_for_chat, sanitize_response

logger = logging.getLogger(__name__)

# Context window requested from Ollama, in tokens. Ollama allocates the KV cache
# for the whole window up front, so this is a memory budget, not just a limit.
# The largest prompt this app builds is a 20,000-character page excerpt (about
# 5k tokens), three retrieved documents and ten turns of history.
NUM_CTX = 16384


class OllamaProvider(LLMProvider):
    """Ollama provider for local LLM models"""

    def __init__(
        self,
        model_name: str = DEFAULT_MODELS["ollama"],
        base_url: str = "http://localhost:11434",
    ):
        super().__init__("ollama")
        self.model = model_name
        self.base_url = base_url.rstrip("/")

    def is_available(self) -> bool:
        """Check if Ollama is running and the model is pulled"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=2)
            if response.status_code != 200:
                return False

            model_names = [m.get("name", "") for m in response.json().get("models", [])]
            available = any(
                self.model == name or self.model.split(":")[0] == name.split(":")[0]
                for name in model_names
            )
            if not available:
                logger.warning(
                    f"Model {self.model} not found in Ollama. Available models: {model_names}"
                )
            return available

        except Exception as e:
            logger.error(f"Ollama not available: {e}")
            return False

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        Chat with the Ollama model.

        Args:
            messages: List of message dicts with 'role' and 'content'
            **kwargs: system_prompt, temperature, max_tokens

        Returns:
            Model response

        Raises:
            LLMError: If Ollama fails or times out
        """
        formatted_messages = format_messages_for_chat(
            messages,
            system_prompt=kwargs.get("system_prompt")
            or "You are a helpful AI assistant.",
        )

        data: Dict[str, Any] = {
            "model": self.model,
            "messages": formatted_messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
                "num_predict": kwargs.get("max_tokens", 4000),
                "num_ctx": NUM_CTX,
            },
        }

        # Local models are slow on long prompts: roughly 1 s per 200 characters,
        # clamped to 60..300 s.
        total_chars = sum(len(msg.get("content", "")) for msg in formatted_messages)
        timeout = max(60, min(300, total_chars // 200))

        try:
            response = requests.post(
                f"{self.base_url}/api/chat", json=data, timeout=timeout
            )
        except requests.exceptions.Timeout:
            logger.error(f"Ollama did not answer within {timeout} s")
            raise LLMError("The local AI model did not answer in time.")
        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama request failed: {e}")
            raise LLMError("The local AI model cannot be reached right now.")

        if response.status_code != 200:
            logger.error(
                f"Ollama API error: {response.status_code} - {response.text[:200]}"
            )
            raise LLMError("The local AI model could not process this request.")

        content = response.json().get("message", {}).get("content", "")
        if not content:
            logger.error("Empty response from Ollama")
            raise LLMError("The local AI model returned no answer.")

        return sanitize_response(content)
