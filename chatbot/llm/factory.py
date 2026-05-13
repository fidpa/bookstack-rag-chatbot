"""LLM provider factory — picks Azure or Ollama based on env config."""

import logging
import os
from typing import Optional, Dict
from flask import session
from .base import LLMProvider
from .providers.ollama import OllamaProvider
from .providers.azure import AzureProvider
from .models import DEFAULT_MODELS, get_available_models

logger = logging.getLogger(__name__)

# Ollama Security Lock - must be explicitly enabled
ENABLE_OLLAMA = os.getenv('ENABLE_OLLAMA_FALLBACK', 'false').lower() == 'true'


def create_llm_provider(provider_type: Optional[str] = None) -> LLMProvider:
    """
    Create an LLM provider instance
    
    Args:
        provider_type: Type of provider ('ollama', 'azure', 'auto', or None)
                      If None or 'auto', will auto-detect best available provider
    
    Returns:
        LLMProvider instance
        
    Raises:
        ValueError: If no provider is available
    """
    logger.info(f"Creating LLM provider: {provider_type}")
    
    # Get provider type from session if not specified
    if not provider_type:
        provider_type = session.get('llm_provider', 'auto')
    
    # Specific provider requested
    if provider_type == 'ollama':
        if not ENABLE_OLLAMA:
            raise ValueError("Ollama ist deaktiviert. Setzen Sie ENABLE_OLLAMA_FALLBACK=true um Ollama zu aktivieren.")

        model_name = session.get('ollama_model', DEFAULT_MODELS['ollama'])
        base_url = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
        provider = OllamaProvider(model_name=model_name, base_url=base_url)
        if provider.is_available():
            logger.info(f"Using Ollama provider with model: {model_name}")
            return provider
        else:
            raise ValueError("Ollama provider requested but not available")
    
    elif provider_type == 'azure':
        api_key = os.getenv('AZURE_OPENAI_API_KEY')
        endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
        if not api_key or not endpoint:
            raise ValueError("Azure provider requested but credentials not found (AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT required)")
        
        model = session.get('azure_model', DEFAULT_MODELS['azure'])
        provider = AzureProvider()  # AzureProvider reads env vars directly
        if provider.is_available():
            logger.info(f"Using Azure provider with model: {model}")
            return provider
        else:
            raise ValueError("Azure provider requested but not available")
    
    # Auto-detect best available provider
    elif provider_type in ['auto', None]:
        # Try Azure first (preferred for production)
        try:
            api_key = os.getenv('AZURE_OPENAI_API_KEY')
            endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
            if api_key and endpoint:
                azure = AzureProvider()
                if azure.is_available():
                    logger.info("Auto-selected Azure provider")
                    session['llm_provider'] = 'azure'
                    return azure
        except Exception as e:
            logger.debug(f"Azure not available: {str(e)}")

        # Try Ollama as fallback (only if explicitly enabled)
        if ENABLE_OLLAMA:
            try:
                base_url = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
                ollama = OllamaProvider(base_url=base_url)
                if ollama.is_available():
                    logger.info("Auto-selected Ollama provider (ENABLE_OLLAMA_FALLBACK=true)")
                    session['llm_provider'] = 'ollama'
                    return ollama
            except Exception as e:
                logger.debug(f"Ollama not available: {str(e)}")
        else:
            logger.info("Ollama fallback disabled (set ENABLE_OLLAMA_FALLBACK=true to enable)")

        # No providers available - raise error
        if ENABLE_OLLAMA:
            raise ValueError("Kein LLM-Provider verfügbar. Bitte Azure OpenAI konfigurieren oder Ollama starten.")
        else:
            raise ValueError("Azure OpenAI nicht verfügbar. Ollama ist deaktiviert (ENABLE_OLLAMA_FALLBACK=false).")
    
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")


def get_available_providers() -> Dict[str, bool]:
    """
    Check which providers are available
    
    Returns:
        Dict mapping provider names to availability status
    """
    providers = {}
    
    # Check Ollama (only if enabled)
    if ENABLE_OLLAMA:
        try:
            base_url = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
            ollama = OllamaProvider(base_url=base_url)
            providers['ollama'] = ollama.is_available()
        except Exception:
            providers['ollama'] = False
    else:
        providers['ollama'] = False  # Disabled by security lock

    # Check Azure
    try:
        api_key = os.getenv('AZURE_OPENAI_API_KEY')
        endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
        if api_key and endpoint:
            azure = AzureProvider()
            providers['azure'] = azure.is_available()
        else:
            providers['azure'] = False
    except Exception:
        providers['azure'] = False
    
    
    return providers


def get_provider_info(provider_type: str) -> Dict:
    """
    Get information about a specific provider
    
    Args:
        provider_type: Provider type
        
    Returns:
        Provider information dict
    """
    try:
        if provider_type == 'ollama':
            provider = OllamaProvider()
        elif provider_type == 'azure':
            provider = AzureProvider()
        else:
            return {'error': f'Unknown provider: {provider_type}'}

        return provider.get_info()
    except Exception as e:
        return {'error': str(e)}


def get_all_models() -> Dict[str, list]:
    """
    Get all available models grouped by provider
    
    Returns:
        Dict with provider names as keys and model lists as values
    """
    from .models import OLLAMA_MODELS, AZURE_MODELS, MODEL_DISPLAY_ORDER
    
    result = {}
    
    # Get Ollama models
    ollama_models = []
    for model_id in MODEL_DISPLAY_ORDER['ollama']:
        if model_id in OLLAMA_MODELS:
            model_info = OLLAMA_MODELS[model_id].copy()
            model_info['id'] = model_id
            ollama_models.append(model_info)
    result['ollama'] = ollama_models
    
    # Get Azure models
    azure_models = []
    for model_id in MODEL_DISPLAY_ORDER['azure']:
        if model_id in AZURE_MODELS:
            model_info = AZURE_MODELS[model_id].copy()
            model_info['id'] = model_id
            azure_models.append(model_info)
    result['azure'] = azure_models
    
    return result