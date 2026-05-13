"""Common utility functions for LLM provider operations."""

import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def format_messages_for_chat(messages: List[Dict[str, str]], system_prompt: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Format messages for chat APIs
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        system_prompt: Optional system prompt to prepend
        
    Returns:
        Formatted messages list
    """
    formatted_messages = []
    
    # Add system prompt if provided
    if system_prompt:
        formatted_messages.append({
            'role': 'system',
            'content': system_prompt
        })
    
    # Add conversation messages
    for msg in messages:
        if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
            formatted_messages.append({
                'role': msg['role'],
                'content': msg['content']
            })
    
    return formatted_messages


def truncate_messages(messages: List[Dict[str, str]], max_messages: int = 10) -> List[Dict[str, str]]:
    """
    Truncate messages to keep only the most recent ones
    
    Args:
        messages: List of messages
        max_messages: Maximum number of messages to keep
        
    Returns:
        Truncated messages list
    """
    if len(messages) <= max_messages:
        return messages
    
    # Keep the most recent messages
    return messages[-max_messages:]


def estimate_tokens(text: str) -> int:
    """
    Rough estimation of token count
    
    Args:
        text: Input text
        
    Returns:
        Estimated token count
    """
    # Simple estimation: ~1 token per 4 characters
    return len(text) // 4


def sanitize_response(response: str) -> str:
    """
    Clean up AI response while preserving markdown formatting
    
    Args:
        response: Raw AI response
        
    Returns:
        Cleaned response
    """
    # Remove excessive whitespace but preserve line breaks for markdown
    response = response.strip()
    
    # Don't remove markdown code blocks - they should be rendered properly
    # Only remove if it's a single code block wrapping the entire response
    # This handles cases where LLMs wrap their entire response in ```
    if response.startswith("```") and response.endswith("```"):
        # Count occurrences to ensure it's just a wrapper
        count = response.count("```")
        if count == 2:
            # It's likely just a wrapper, remove it
            response = response[3:-3].strip()
    
    # Remove excessive blank lines (more than 2 consecutive)
    while '\n\n\n' in response:
        response = response.replace('\n\n\n', '\n\n')
    
    return response


def build_system_prompt(user=None) -> str:
    """
    Build system prompt for Widget-Only architecture

    Args:
        user: Deprecated - Widget-Only has no user objects

    Returns:
        System prompt string
    """
    # Widget-Only: Simple base prompt without user personalization
    return "You are a helpful AI assistant for a BookStack wiki."