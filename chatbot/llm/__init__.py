"""LLM package: provider abstractions and helpers."""

from .base import LLMProvider
from .models import OLLAMA_MODELS, AZURE_MODELS

__all__ = ['LLMProvider', 'get_provider_models', 'is_provider_available', 'get_llm_provider']

def get_provider_models(provider):
    """
    Get list of available models for a provider

    Args:
        provider: Provider name ('ollama' or 'azure')
        
    Returns:
        List of model IDs
    """
    if provider == 'ollama':
        return list(OLLAMA_MODELS.keys())
    elif provider == 'azure':
        return list(AZURE_MODELS.keys())
    else:
        return []

def is_provider_available(provider):
    """
    Check if a provider is available

    Args:
        provider: Provider name ('ollama' or 'azure')
        
    Returns:
        Boolean indicating availability
    """
    try:
        if provider == 'ollama':
            from .providers.ollama import OllamaProvider
            # Try to create provider instance
            OllamaProvider()
            return True
        elif provider == 'azure':
            import os
            # Check if Azure credentials are set
            return bool(os.getenv('AZURE_OPENAI_API_KEY') and os.getenv('AZURE_OPENAI_ENDPOINT'))
        else:
            return False
    except Exception:
        return False

def get_llm_provider(provider_name):
    """
    Get an LLM provider instance

    Args:
        provider_name: Provider name ('ollama' or 'azure')
        
    Returns:
        LLMProvider instance or None
    """
    try:
        if provider_name == 'ollama':
            from .providers.ollama import OllamaProvider
            return OllamaProvider()
        elif provider_name == 'azure':
            from .providers.azure import AzureProvider
            return AzureProvider()
        else:
            return None
    except Exception:
        return None