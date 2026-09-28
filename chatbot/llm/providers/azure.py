"""Azure OpenAI provider implementing the LLMProvider interface."""

import os
import logging
from typing import List, Dict

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from llm.base import LLMError, LLMProvider
from llm.models import DEFAULT_MODELS

logger = logging.getLogger(__name__)

try:
    from openai import (
        AzureOpenAI,
        APIConnectionError,
        AuthenticationError,
        BadRequestError,
        RateLimitError,
    )

    AZURE_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - openai is a hard requirement
    AZURE_SDK_AVAILABLE = False
    logger.warning("Azure OpenAI SDK not installed. Install with: pip install openai")

# Seconds per request attempt. The SDK default is 600 s with two silent internal
# retries; with four waitress threads a handful of hung calls would stall the app.
REQUEST_TIMEOUT = 60
ATTEMPTS = 3


class AzureProvider(LLMProvider):
    """Azure OpenAI API Provider"""

    def __init__(self):
        super().__init__(name="azure")

        self.client = None
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
        self.model = (
            os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or DEFAULT_MODELS["azure"]
        )

        if AZURE_SDK_AVAILABLE and self.api_key and self.endpoint:
            try:
                self.client = AzureOpenAI(
                    api_key=self.api_key,
                    api_version=self.api_version,
                    azure_endpoint=self.endpoint,
                    timeout=REQUEST_TIMEOUT,
                    max_retries=0,  # tenacity below owns retrying
                )
                logger.info(
                    f"Azure OpenAI provider initialised with endpoint: {self.endpoint}"
                )
            except Exception as e:
                logger.error(f"Failed to initialise Azure OpenAI client: {e}")
                self.client = None

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(ATTEMPTS),
        retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        # Re-raise the last error instead of tenacity's RetryError, so the
        # handlers in chat() see the real exception type.
        reraise=True,
    )
    def _make_api_call(self, messages: List[Dict], temperature: float, max_tokens: int):
        return self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        system_prompt: str = "",
        **kwargs,
    ) -> str:
        """
        Send a chat request to Azure OpenAI.

        Raises:
            LLMError: With a short message that is safe to show to a wiki
                visitor; the detail is logged here.
        """
        if not self.client:
            raise LLMError("The AI service is not configured.")

        formatted = []
        if system_prompt:
            formatted.append({"role": "system", "content": system_prompt})
        formatted.extend(
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in messages
        )

        try:
            response = self._make_api_call(formatted, temperature, max_tokens)
            if response and response.choices:
                return response.choices[0].message.content or ""
            logger.error("No valid response received from Azure OpenAI")
            raise LLMError("The AI service returned no answer. Please try again.")

        except LLMError:
            raise

        except AuthenticationError as e:
            logger.error(f"Azure OpenAI authentication error: {e}")
            raise LLMError("The AI service rejected the configured credentials.")

        except BadRequestError as e:
            logger.error(f"Azure OpenAI bad request: {e}")
            error_msg = str(e).lower()
            if "deployment" in error_msg and "not found" in error_msg:
                raise LLMError("The configured AI deployment was not found.")
            if "content" in error_msg and "filter" in error_msg:
                raise LLMError(
                    "The request was blocked by the content filter. Please rephrase."
                )
            raise LLMError("The AI service could not process this request.")

        except RateLimitError as e:
            logger.error(f"Azure OpenAI rate limit after {ATTEMPTS} attempts: {e}")
            raise LLMError("The AI service is busy. Please try again in a minute.")

        except APIConnectionError as e:
            logger.error(
                f"Azure OpenAI connection error after {ATTEMPTS} attempts: {e}"
            )
            raise LLMError("The AI service cannot be reached right now.")

        except Exception as e:
            logger.error(f"Unexpected Azure OpenAI error: {e}")
            raise LLMError("The AI service could not process this request.")

    def is_available(self) -> bool:
        """True when credentials are set and the client initialised (no network call)."""
        return self.client is not None
