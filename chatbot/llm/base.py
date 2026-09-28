"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod
from typing import List, Dict


class LLMError(RuntimeError):
    """A failed model call. The message is safe to show to a wiki visitor;
    the technical detail goes to the log where the error is raised."""


class LLMProvider(ABC):
    """A chat model behind one API: Azure OpenAI or Ollama."""

    #: Model or deployment identifier, reported in logs
    model: str = ""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        Answer a conversation.

        Args:
            messages: Message dicts with 'role' and 'content'
            **kwargs: system_prompt, temperature, max_tokens

        Returns:
            The model's reply

        Raises:
            LLMError: If the model could not answer
        """

    @abstractmethod
    def is_available(self) -> bool:
        """True if the provider can take a request right now."""
