"""Common utility functions for LLM provider operations."""

from typing import List, Dict, Optional


def format_messages_for_chat(
    messages: List[Dict[str, str]], system_prompt: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Format messages for chat APIs

    Args:
        messages: List of message dicts with 'role' and 'content'
        system_prompt: Optional system prompt to prepend

    Returns:
        Formatted messages list
    """
    formatted_messages = []

    if system_prompt:
        formatted_messages.append({"role": "system", "content": system_prompt})

    for msg in messages:
        if isinstance(msg, dict) and "role" in msg and "content" in msg:
            formatted_messages.append({"role": msg["role"], "content": msg["content"]})

    return formatted_messages


def sanitize_response(response: str) -> str:
    """
    Clean up AI response while preserving markdown formatting

    Args:
        response: Raw AI response

    Returns:
        Cleaned response
    """
    response = response.strip()

    # Unwrap a reply the model wrapped entirely in one code fence
    if (
        response.startswith("```")
        and response.endswith("```")
        and response.count("```") == 2
    ):
        response = response[3:-3].strip()

    while "\n\n\n" in response:
        response = response.replace("\n\n\n", "\n\n")

    return response
