"""Supported LLM model constants for Ollama and Azure OpenAI."""

# Ollama Models (Local) - Nur tatsächlich installierte Modelle
OLLAMA_MODELS = {
    # Mittlere Modelle (beste Balance)
    "mistral:latest": {
        "name": "Mistral 7B",
        "size": "4.1 GB",
        "description": "Mistral AI's base model - ausgewogen und zuverlässig",
        "context_length": 32768,  # 32k context
        "recommended": True,
    },
    "llama3.1:latest": {
        "name": "Llama 3.1 8B",
        "size": "4.9 GB",
        "description": "Meta's Llama 3.1 - stark aber etwas langsamer",
        "context_length": 128000,  # 128k context
        "recommended": True,
    },
    "llama2:latest": {
        "name": "Llama 2 7B",
        "size": "3.8 GB",
        "description": "Meta's Llama 2 - älter aber stabil",
        "context_length": 4096,  # 4k context
        "recommended": False,
    },
    # Kleine Modelle (schnell)
    "llama3.2:3b": {
        "name": "Llama 3.2 3B",
        "size": "2.0 GB",
        "description": "Meta's efficient Llama 3.2 - schnell und modern",
        "context_length": 128000,  # 128k context
        "recommended": True,
    },
    "llama3.2:latest": {
        "name": "Llama 3.2 Latest",
        "size": "2.0 GB",
        "description": "Alias für Llama 3.2 3B - schnell und modern",
        "context_length": 128000,  # 128k context
        "recommended": True,
    },
    "llama3.2:1b": {
        "name": "Llama 3.2 1B",
        "size": "1.3 GB",
        "description": "Meta's smallest Llama 3.2 - sehr schnell",
        "context_length": 128000,  # 128k context
        "recommended": False,  # Weniger genau
    },
}


# Azure OpenAI Models (API)
AZURE_MODELS = {
    "azure-gpt-4o": {
        "name": "Azure GPT-4o",
        "description": "Neuestes multimodales GPT-4 Omni Modell",
        "size": "200B+",  # Geschätzt
        "context_length": 128000,  # 128k context
        "recommended": True,
    },
    "azure-gpt-4": {
        "name": "Azure GPT-4",
        "description": "OpenAI GPT-4 über Azure",
        "size": "175B+",  # Geschätzt
        "context_length": 8192,  # 8k context
        "recommended": True,
    },
    "azure-gpt-35-turbo": {
        "name": "Azure GPT-3.5 Turbo",
        "description": "Schnelles und kosteneffizientes GPT-3.5",
        "size": "20B",  # Geschätzt
        "context_length": 4096,  # 4k context (standard), kann auf 16k erweitert werden
        "recommended": True,
    },
    "azure-gpt-4-vision": {
        "name": "Azure GPT-4 Vision",
        "description": "GPT-4 mit Bildverständnis",
        "size": "175B+",  # Geschätzt
        "context_length": 128000,  # 128k context
        "recommended": False,  # Teurer
    },
    "azure-gpt-4-turbo": {
        "name": "Azure GPT-4 Turbo",
        "description": "Optimierte Version von GPT-4",
        "size": "175B+",  # Geschätzt
        "context_length": 128000,  # 128k context
        "recommended": True,
    },
}

# Default models for each provider
DEFAULT_MODELS = {
    "ollama": "mistral:latest",  # Mistral 7B als Standard - verfügbar und ausgewogen
    "azure": "azure-gpt-35-turbo",  # GPT-3.5 Turbo als Standard
}

# Model display order (most recommended first) - nur installierte Modelle
MODEL_DISPLAY_ORDER = {
    "ollama": [
        "mistral:latest",  # Default: Beste Balance zwischen Geschwindigkeit und Qualität
        "llama3.1:latest",  # Stärker aber langsamer
        "llama3.2:3b",  # Schnell und modern
        "llama3.2:latest",  # Alias für 3b
        "llama2:latest",  # Älter aber stabil
        "llama3.2:1b",  # Sehr schnell, weniger genau
    ],
    "azure": [
        "azure-gpt-4o",  # Neuestes Modell (Default)
        "azure-gpt-35-turbo",  # Günstig & schnell
        "azure-gpt-4",  # Standard GPT-4
        "azure-gpt-4-turbo",  # Optimierte Version
        "azure-gpt-4-vision",  # Mit Bildverständnis
    ],
}


def get_model_info(provider: str, model_id: str) -> dict:
    """Get information about a specific model"""
    if provider == "ollama":
        return OLLAMA_MODELS.get(
            model_id, {"name": model_id, "description": "Unknown model"}
        )
    elif provider == "azure":
        return AZURE_MODELS.get(
            model_id, {"name": model_id, "description": "Unknown model"}
        )
    return {"name": model_id, "description": "Unknown model"}


def get_available_models(provider: str) -> list:
    """Get list of available models for a provider"""
    if provider == "ollama":
        return list(OLLAMA_MODELS.keys())
    elif provider == "azure":
        return list(AZURE_MODELS.keys())
    return []


def get_default_model(provider: str) -> str:
    """Get default model for a provider"""
    return DEFAULT_MODELS.get(provider, "")
