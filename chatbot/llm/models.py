"""Default model per LLM provider."""

DEFAULT_MODELS = {
    # Overridden by OLLAMA_MODEL
    "ollama": "mistral:latest",
    # Azure routes by deployment; AZURE_OPENAI_DEPLOYMENT_NAME overrides this
    "azure": "gpt-35-turbo",
}
