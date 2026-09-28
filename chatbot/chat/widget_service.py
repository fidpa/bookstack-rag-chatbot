"""
Widget Service - Handles chat functionality for BookStack widget
No authentication required - BookStack handles user auth
"""

import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from llm.base import LLMError
from llm.factory import get_llm_provider
from .context_builder import ChatContextBuilder

logger = logging.getLogger(__name__)

# Session timeout in seconds (30 minutes)
SESSION_TIMEOUT = 1800
# Upper bound on sessions held in memory; the oldest are dropped first
MAX_SESSIONS = 5000
# Messages kept per session, and how many of them go to the model
MAX_STORED_MESSAGES = 20
HISTORY_MESSAGES = 10

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant with access to two knowledge sources:\n\n"
    "1. **Knowledge Base**: uploaded documents (PDF, DOCX, Markdown)\n"
    "2. **BookStack wiki**: team documentation pages\n\n"
    "Instructions:\n"
    "- Use ALL available sources. Prefer the most specific source for each claim.\n"
    "- When the user asks about 'this page', refer to the current page context.\n"
    "- Always cite sources briefly: e.g. 'according to the Onboarding wiki page' "
    "or 'from the uploaded document'.\n"
    "- Never quote long formal titles verbatim from the context — use a short description.\n"
    "- Combine information from multiple sources when they complement each other.\n"
    "- If the sources do not contain an answer, say so explicitly.\n"
    "- Respond in the same language the user writes in."
)


def get_system_prompt() -> str:
    """CHATBOT_SYSTEM_PROMPT, or the built-in prompt when unset or empty.

    docker-compose.yml passes the variable through as an empty string when it
    is not set, so an empty value has to mean "use the default" as well.
    """
    return os.getenv("CHATBOT_SYSTEM_PROMPT", "").strip() or DEFAULT_SYSTEM_PROMPT


class WidgetSessionManager:
    """In-memory conversation history per widget session, shared by all threads."""

    _sessions: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    _lock = threading.Lock()

    @classmethod
    def get_or_create_session(cls, session_id: Optional[str] = None) -> str:
        """
        Return session_id if it is a live session, otherwise start a new one.

        Only ids this server issued are accepted; a client cannot choose its own.
        """
        now = time.time()
        with cls._lock:
            expired = [
                sid
                for sid, data in cls._sessions.items()
                if now - data["last_activity"] > SESSION_TIMEOUT
            ]
            for sid in expired:
                del cls._sessions[sid]

            if session_id and session_id in cls._sessions:
                cls._sessions[session_id]["last_activity"] = now
                cls._sessions.move_to_end(session_id)
                return session_id

            while len(cls._sessions) >= MAX_SESSIONS:
                cls._sessions.popitem(last=False)

            new_session_id = str(uuid.uuid4())
            cls._sessions[new_session_id] = {
                "created": now,
                "last_activity": now,
                "messages": [],
            }
            return new_session_id

    @classmethod
    def add_message(cls, session_id: str, role: str, content: str):
        """Append a message, keeping the last MAX_STORED_MESSAGES."""
        with cls._lock:
            session = cls._sessions.get(session_id)
            if session is not None:
                session["messages"].append({"role": role, "content": content})
                del session["messages"][:-MAX_STORED_MESSAGES]

    @classmethod
    def get_messages(cls, session_id: str) -> List[Dict[str, str]]:
        """A copy of the session's message history."""
        with cls._lock:
            session = cls._sessions.get(session_id)
            return list(session["messages"]) if session else []

    @classmethod
    def clear(cls):
        """Drop every session (used by tests)."""
        with cls._lock:
            cls._sessions.clear()


def process_widget_message(
    message: str,
    session_id: Optional[str] = None,
    bookstack_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Process chat message from widget

    Args:
        message: User message
        session_id: Session id the server issued earlier, if any
        bookstack_context: Current BookStack page context

    Returns:
        Response dict with AI response and session info
    """
    if not message or not message.strip():
        return {"success": False, "error": "Message cannot be empty"}

    try:
        session_id = WidgetSessionManager.get_or_create_session(session_id)
        history = WidgetSessionManager.get_messages(session_id)

        response_start = time.time()
        ai_response, ok = generate_widget_response(message, history, bookstack_context)
        response_time_ms = int((time.time() - response_start) * 1000)

        # A failed turn stays out of the history, so an error text is never fed
        # back to the model as if it had said it.
        if ok:
            WidgetSessionManager.add_message(session_id, "user", message)
            WidgetSessionManager.add_message(session_id, "assistant", ai_response)

        return {
            "success": True,
            "response": ai_response,
            "session_id": session_id,
            "timestamp": int(time.time()),
            "response_time_ms": response_time_ms,
        }

    except Exception as e:
        logger.error(f"Error processing widget message: {e}", exc_info=True)
        return {"success": False, "error": "Failed to process message"}


def generate_widget_response(
    user_message: str,
    history: List[Dict[str, str]],
    bookstack_context: Optional[Dict[str, Any]] = None,
) -> Tuple[str, bool]:
    """
    Generate the answer to one widget message.

    Args:
        user_message: The visitor's question
        history: Earlier turns of this session, oldest first
        bookstack_context: The page the visitor is on, as sent by the widget

    Returns:
        (answer, ok): ok is False when the answer is an error notice
    """
    provider = get_llm_provider()
    if provider is None:
        return (
            "Sorry, no AI service is currently available. Please try again later.",
            False,
        )

    try:
        # Retrieval runs on the question alone. The page the visitor is on goes
        # into the context in full (see ChatContextBuilder); mixing its text into
        # the search query would make keyword extraction pick terms from the page
        # instead of from the question.
        combined_context = ChatContextBuilder.build_combined_context(
            user_message, bookstack_context
        )

        llm_messages: List[Dict[str, str]] = []
        if combined_context:
            llm_messages.append(
                {
                    "role": "system",
                    "content": f"Relevant context from knowledge base:\n{combined_context}",
                }
            )
        llm_messages.extend(history[-HISTORY_MESSAGES:])
        llm_messages.append({"role": "user", "content": user_message})

        logger.info(
            f"Widget LLM request: {len(llm_messages)} messages, "
            f"{len(combined_context)} context chars, provider {provider.name}"
        )

        response = provider.chat(llm_messages, system_prompt=get_system_prompt())
        return response, True

    except LLMError as e:
        return str(e), False
    except Exception as e:
        logger.error(f"Error generating widget response: {e}", exc_info=True)
        return "Sorry, I could not process your request. Please try again.", False
