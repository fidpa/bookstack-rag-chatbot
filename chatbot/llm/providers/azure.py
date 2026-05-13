"""Azure OpenAI provider implementing the LLMProvider interface."""

import os
import logging
from typing import List, Dict

from llm.base import LLMProvider

# Retry-Mechanismen
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)

# Azure OpenAI SDK importieren
try:
    from openai import AzureOpenAI
    from openai import (
        APIError,
        APIConnectionError,
        RateLimitError,
        AuthenticationError,
        BadRequestError,
    )

    AZURE_SDK_AVAILABLE = True
except ImportError:
    AZURE_SDK_AVAILABLE = False
    logger.warning("Azure OpenAI SDK not installed. Install with: pip install openai")

    # Dummy exceptions for the case where the SDK is not installed
    class APIError(Exception):
        pass

    class APIConnectionError(Exception):
        pass

    class RateLimitError(Exception):
        pass

    class AuthenticationError(Exception):
        pass

    class BadRequestError(Exception):
        pass


class AzureProvider(LLMProvider):
    """Azure OpenAI API Provider"""

    def __init__(self):
        """Initialize Azure OpenAI provider"""
        super().__init__(name="azure")

        self.client = None
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")

        # Only initialize client if credentials are available
        if AZURE_SDK_AVAILABLE and self.api_key and self.endpoint:
            try:
                self.client = AzureOpenAI(
                    api_key=self.api_key,
                    api_version=self.api_version,
                    azure_endpoint=self.endpoint,
                )
                logger.info(
                    f"Azure OpenAI provider initialised with endpoint: {self.endpoint}"
                )
            except Exception as e:
                logger.error(f"Failed to initialise Azure OpenAI client: {str(e)}")
                self.client = None
        else:
            if not AZURE_SDK_AVAILABLE:
                logger.warning("Azure OpenAI SDK not installed")
            if not self.api_key:
                logger.debug("AZURE_OPENAI_API_KEY not set")
            if not self.endpoint:
                logger.debug("AZURE_OPENAI_ENDPOINT not set")

    def _get_deployment_name(self, model_id: str) -> str:
        """
        Map model ID to Azure deployment name

        Args:
            model_id: The model ID (e.g., 'azure-gpt-4')

        Returns:
            The deployment name for Azure
        """
        # AZURE_OPENAI_DEPLOYMENT_NAME is the canonical override — always use it
        env_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        if env_deployment:
            return env_deployment

        # Fallback: strip 'azure-' prefix to derive a sensible deployment name
        if model_id.startswith("azure-"):
            return model_id[6:]
        return model_id

    @retry(
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(6),
        retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _make_api_call(
        self,
        deployment_name: str,
        messages: List[Dict],
        temperature: float,
        max_tokens: int,
        **kwargs,
    ):
        """Internal method with retry logic for API calls"""
        return self.client.chat.completions.create(
            model=deployment_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = "azure-gpt-35-turbo",
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs,
    ) -> str:
        """
        Send chat request to Azure OpenAI

        Args:
            messages: List of message dictionaries with 'role' and 'content'
            model: Model ID to use
            temperature: Temperature for response generation
            max_tokens: Maximum tokens in response
            **kwargs: Additional parameters

        Returns:
            Model response as string
        """
        if not self.client:
            return "Error: Azure OpenAI is not configured. Please set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT."

        try:
            # Get deployment name from model ID
            deployment_name = self._get_deployment_name(model)

            # Extract system_prompt from kwargs if provided
            system_prompt = kwargs.pop("system_prompt", None)

            # Format messages for Azure OpenAI
            formatted_messages = []

            # Add system prompt as first message if provided
            if system_prompt:
                formatted_messages.append({"role": "system", "content": system_prompt})

            # Add all other messages
            for msg in messages:
                formatted_messages.append(
                    {"role": msg.get("role", "user"), "content": msg.get("content", "")}
                )

            # Make API call with retry logic
            response = self._make_api_call(
                deployment_name=deployment_name,
                messages=formatted_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

            # Extract response
            if response and response.choices and len(response.choices) > 0:
                return response.choices[0].message.content
            else:
                logger.error("No valid response received from Azure OpenAI")
                return "Error: no response received from the Azure OpenAI service."

        except AuthenticationError as e:
            logger.error(f"Azure OpenAI authentication error: {str(e)}")
            return "Error: invalid Azure OpenAI API key. Please check AZURE_OPENAI_API_KEY."

        except BadRequestError as e:
            logger.error(f"Azure OpenAI bad request: {str(e)}")
            error_msg = str(e).lower()

            if "deployment" in error_msg and "not found" in error_msg:
                return (
                    f"Error: Azure deployment '{deployment_name}' not found.\n"
                    f"Check the available deployments in the Azure Portal and set "
                    f"AZURE_OPENAI_DEPLOYMENT_NAME in .env to the correct name."
                )
            elif "content" in error_msg and "filter" in error_msg:
                return "Error: the request was blocked by the Azure content filter. Please rephrase."
            else:
                return f"Error: bad request - {str(e)}"

        except RateLimitError as e:
            logger.error(f"Azure OpenAI rate limit: {str(e)}")
            return "Error: Azure OpenAI rate limit reached. The request will be retried automatically..."

        except APIConnectionError as e:
            logger.error(f"Azure OpenAI connection error: {str(e)}")
            return "Error: connection to Azure OpenAI failed. Please check your network connectivity."

        except Exception as e:
            logger.error(f"Unexpected Azure OpenAI error: {str(e)}")
            error_msg = str(e).lower()

            if "403" in error_msg and (
                "firewall" in error_msg or "virtual network" in error_msg
            ):
                return "Error: Azure OpenAI access denied by firewall/VNet rules. Allow the chatbot's IP in the Azure Portal."
            else:
                return f"Error during the Azure OpenAI request: {str(e)}"

    @retry(
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(3),  # fewer retries for streaming
        retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _make_streaming_call(
        self,
        deployment_name: str,
        messages: List[Dict],
        temperature: float,
        max_tokens: int,
        **kwargs,
    ):
        """Internal method with retry logic for streaming API calls"""
        return self.client.chat.completions.create(
            model=deployment_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs,
        )

    def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: str = "azure-gpt-35-turbo",
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs,
    ):
        """
        Stream chat responses from Azure OpenAI

        Args:
            messages: List of message dictionaries
            model: Model ID to use
            temperature: Temperature for response generation
            max_tokens: Maximum tokens in response
            **kwargs: Additional parameters

        Yields:
            Chunks of response text
        """
        if not self.client:
            yield "Error: Azure OpenAI is not configured."
            return

        try:
            # Get deployment name from model ID
            deployment_name = self._get_deployment_name(model)

            # Extract system_prompt from kwargs if provided
            system_prompt = kwargs.pop("system_prompt", None)

            # Format messages
            formatted_messages = []

            # Add system prompt as first message if provided
            if system_prompt:
                formatted_messages.append({"role": "system", "content": system_prompt})

            # Add all other messages
            for msg in messages:
                formatted_messages.append(
                    {"role": msg.get("role", "user"), "content": msg.get("content", "")}
                )

            # Make streaming API call with retry logic
            stream = self._make_streaming_call(
                deployment_name=deployment_name,
                messages=formatted_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

            # Yield chunks
            for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content

        except AuthenticationError as e:
            logger.error(f"Azure OpenAI streaming auth error: {str(e)}")
            yield "Error: invalid Azure OpenAI API key."

        except BadRequestError as e:
            logger.error(f"Azure OpenAI streaming bad request: {str(e)}")
            if "content" in str(e).lower() and "filter" in str(e).lower():
                yield "Error: content was blocked by the Azure content filter."
            else:
                yield f"Error: invalid streaming request - {str(e)}"

        except RateLimitError as e:
            logger.error(f"Azure OpenAI streaming rate limit: {str(e)}")
            yield "Error: rate limit reached. Please wait a moment..."

        except Exception as e:
            logger.error(f"Azure OpenAI streaming error: {str(e)}")
            yield f"Streaming error: {str(e)}"

    def complete(
        self,
        prompt: str,
        model: str = "azure-gpt-35-turbo",
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs,
    ) -> str:
        """
        Simple completion API (converts to chat format)

        Args:
            prompt: The prompt text
            model: Model ID to use
            temperature: Temperature for response generation
            max_tokens: Maximum tokens in response
            **kwargs: Additional parameters

        Returns:
            Model response as string
        """
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, model, temperature, max_tokens, **kwargs)

    def get_available_models(self) -> List[str]:
        """
        Get list of available Azure OpenAI models

        Returns:
            List of model IDs
        """
        # Return predefined list since Azure doesn't provide a models API
        from llm.models import AZURE_MODELS

        return list(AZURE_MODELS.keys())

    def validate_model(self, model_id: str) -> bool:
        """
        Check if a model is available

        Args:
            model_id: Model ID to check

        Returns:
            True if model is available
        """
        from llm.models import AZURE_MODELS

        return model_id in AZURE_MODELS

    def is_available(self) -> bool:
        """
        Check if Azure provider is available

        Returns:
            True if API key and endpoint are configured and client is initialized
        """
        return bool(self.client is not None)
