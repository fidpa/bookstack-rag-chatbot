"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Base class for LLM providers - minimal and simple"""
    
    def __init__(self, name: str, config: dict = None):
        """
        Initialize LLM provider
        
        Args:
            name: Provider name (ollama, claude, etc.)
            config: Optional configuration dictionary
        """
        self.name = name
        self.config = config or {}
        logger.info(f"Initializing {name} provider")
    
    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        Chat with message history
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            **kwargs: Additional provider-specific parameters
            
        Returns:
            str: AI response
        """
        pass
    
    @abstractmethod
    def complete(self, prompt: str, **kwargs) -> str:
        """
        Simple text completion
        
        Args:
            prompt: Text prompt
            **kwargs: Additional provider-specific parameters
            
        Returns:
            str: AI completion
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if provider is available
        
        Returns:
            bool: True if provider is available
        """
        pass
    
    def get_info(self) -> Dict[str, Any]:
        """
        Get provider information
        
        Returns:
            Dict with provider info
        """
        return {
            'name': self.name,
            'available': self.is_available(),
            'config': self.config
        }


