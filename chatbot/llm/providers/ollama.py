"""Ollama provider — local LLM integration over the Ollama HTTP API."""

import logging
import requests
from typing import List, Dict
from ..base import LLMProvider
from ..utils import format_messages_for_chat, sanitize_response

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    """Ollama provider for local LLM models"""
    
    def __init__(self, model_name: str = "llama3.2:1b", base_url: str = "http://localhost:11434"):
        """
        Initialize Ollama provider
        
        Args:
            model_name: Ollama model name (default: llama3.2:1b)
            base_url: Ollama API base URL
        """
        super().__init__("ollama", {
            'model_name': model_name,
            'base_url': base_url
        })
        self.model_name = model_name
        self.base_url = base_url.rstrip('/')
    
    def is_available(self) -> bool:
        """Check if Ollama is running and model is available"""
        try:
            # Check if Ollama is running
            response = requests.get(f"{self.base_url}/api/tags", timeout=2)
            if response.status_code != 200:
                return False
            
            # Check if our model is available
            models = response.json().get('models', [])
            model_names = [m.get('name', '') for m in models]
            
            # Check exact match or base model name
            available = any(
                self.model_name == name or 
                self.model_name.split(':')[0] == name.split(':')[0]
                for name in model_names
            )
            
            if not available:
                logger.warning(f"Model {self.model_name} not found in Ollama. Available models: {model_names}")
            
            return available
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama not available: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Error checking Ollama availability: {str(e)}")
            return False
    
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        Chat with Ollama model
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            **kwargs: Additional parameters (temperature, max_tokens, etc.)
            
        Returns:
            Model response
        """
        try:
            # Format messages for Ollama
            formatted_messages = format_messages_for_chat(
                messages, 
                system_prompt=kwargs.get('system_prompt', "You are a helpful AI assistant.")
            )
            
            # Prepare request
            options = {
                'temperature': kwargs.get('temperature', 0.7),
                'num_predict': kwargs.get('max_tokens', 4000),  # More tokens for detailed responses
                'num_ctx': 128000,  # Reduce from 1024000 to 128000
            }
            
            # Add num_gpu for Mistral-Nemo to force GPU usage
            if 'mistral' in self.model_name.lower():
                options['num_gpu'] = 40  # Mistral-Nemo has 40 layers
            
            data = {
                'model': self.model_name,
                'messages': formatted_messages,
                'stream': False,  # No streaming for simplicity
                'options': options
            }
            
            # Make request with dynamic timeout based on context size
            # Estimate timeout based on message size (rough estimate: 1 sec per 1000 chars)
            total_chars = sum(len(msg.get('content', '')) for msg in formatted_messages)
            # Increase timeout for Mistral-Nemo with GPU loading
            if 'mistral-nemo' in self.model_name.lower():
                dynamic_timeout = max(120, min(300, total_chars // 100))  # Min 120s for Mistral-Nemo
            else:
                dynamic_timeout = max(60, min(300, total_chars // 200))  # Min 60s, max 300s
            
            logger.debug(f"Using timeout of {dynamic_timeout}s for {total_chars} chars")
            logger.info(f"Sending request to Ollama with num_gpu: {data['options'].get('num_gpu', 'not set')}")
            
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=data,
                timeout=dynamic_timeout
            )
            
            if response.status_code != 200:
                logger.error(f"Ollama API error: {response.status_code} - {response.text}")
                raise Exception(f"Ollama API error: {response.status_code}")
            
            # Extract response
            result = response.json()
            content = result.get('message', {}).get('content', '')
            
            if not content:
                logger.error(f"Empty response from Ollama: {result}")
                raise Exception("Empty response from Ollama")
            
            return sanitize_response(content)
            
        except requests.exceptions.Timeout:
            logger.error("Ollama request timed out")
            raise Exception("Die Anfrage an Ollama hat zu lange gedauert. Bitte versuchen Sie es erneut.")
        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama request error: {str(e)}")
            raise Exception(f"Fehler bei der Kommunikation mit Ollama: {str(e)}")
        except Exception as e:
            logger.error(f"Ollama chat error: {str(e)}")
            raise
    
    def complete(self, prompt: str, **kwargs) -> str:
        """
        Simple text completion
        
        Args:
            prompt: Text prompt
            **kwargs: Additional parameters
            
        Returns:
            Completion text
        """
        # Convert to chat format for consistency
        messages = [{'role': 'user', 'content': prompt}]
        return self.chat(messages, **kwargs)
    
    def list_models(self) -> List[str]:
        """Get list of available Ollama models"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=2)
            if response.status_code == 200:
                models = response.json().get('models', [])
                return [m.get('name', '') for m in models if m.get('name')]
            return []
        except Exception:
            return []
    
    def get_info(self) -> Dict:
        """Get provider information"""
        info = super().get_info()
        info['models'] = self.list_models()
        info['current_model'] = self.model_name
        return info