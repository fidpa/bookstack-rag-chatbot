"""
Widget Service - Handles chat functionality for BookStack widget
No authentication required - BookStack handles user auth
"""

import logging
import uuid
import time
import os
from typing import Dict, Any, Optional
from flask import session
from llm.factory import create_llm_provider
from llm.utils import build_system_prompt
from .context_builder import ChatContextBuilder
from .widget_logging import WidgetLogger

logger = logging.getLogger(__name__)

# Ollama Security Lock - must be explicitly enabled
ENABLE_OLLAMA = os.getenv('ENABLE_OLLAMA_FALLBACK', 'false').lower() == 'true'

# Store widget sessions in memory (simple solution for KISS principle)
# In production, could use Redis or database
widget_sessions = {}

# Session timeout in seconds (30 minutes)
SESSION_TIMEOUT = 1800



class WidgetSessionManager:
    """Manages temporary sessions for widget users"""
    
    @staticmethod
    def get_or_create_session(session_id: Optional[str] = None) -> str:
        """Get existing session or create new one"""
        current_time = time.time()
        
        # Clean up expired sessions
        expired = [sid for sid, data in widget_sessions.items() 
                  if current_time - data.get('last_activity', 0) > SESSION_TIMEOUT]
        for sid in expired:
            del widget_sessions[sid]
            logger.info(f"Cleaned up expired widget session: {sid}")
        
        # Validate or create session
        if session_id and session_id in widget_sessions:
            widget_sessions[session_id]['last_activity'] = current_time
            return session_id
        
        # Create new session
        new_session_id = str(uuid.uuid4())
        widget_sessions[new_session_id] = {
            'created': current_time,
            'last_activity': current_time,
            'messages': [],
            'context': {}
        }
        logger.info(f"Created new widget session: {new_session_id}")
        return new_session_id
    
    @staticmethod
    def add_message(session_id: str, role: str, content: str):
        """Add message to session history"""
        if session_id in widget_sessions:
            widget_sessions[session_id]['messages'].append({
                'role': role,
                'content': content,
                'timestamp': time.time()
            })
            # Keep only last 20 messages to prevent memory issues
            if len(widget_sessions[session_id]['messages']) > 20:
                widget_sessions[session_id]['messages'] = widget_sessions[session_id]['messages'][-20:]
    
    @staticmethod
    def get_messages(session_id: str) -> list:
        """Get session message history"""
        if session_id in widget_sessions:
            return widget_sessions[session_id]['messages']
        return []
    
    @staticmethod
    def update_context(session_id: str, context: Dict[str, Any]):
        """Update BookStack context for session"""
        if session_id in widget_sessions:
            widget_sessions[session_id]['context'] = context
            widget_sessions[session_id]['last_activity'] = time.time()


def process_widget_message(
    message: str,
    session_id: Optional[str] = None,
    bookstack_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Process chat message from widget

    Args:
        message: User message
        session_id: Widget session ID (from browser storage)
        bookstack_context: Current BookStack page context

    Returns:
        Response dict with AI response and session info
    """
    start_time = time.time()

    try:
        # Validate message
        if not message or not message.strip():
            return {
                'success': False,
                'error': 'Message cannot be empty'
            }

        # Get or create session
        session_id = WidgetSessionManager.get_or_create_session(session_id)

        # Update context if provided
        if bookstack_context:
            WidgetSessionManager.update_context(session_id, bookstack_context)
            logger.info(f"Updated context for session {session_id}: {bookstack_context.get('title', 'Unknown')}")

        # Log user message to database
        WidgetLogger.log_message(
            session_id=session_id,
            message_type='user',
            content=message,
            bookstack_context=bookstack_context
        )

        # Add user message to in-memory history
        WidgetSessionManager.add_message(session_id, 'user', message)

        # Generate AI response (measure response time)
        response_start = time.time()
        ai_response, provider_info = generate_widget_response(message, session_id, bookstack_context)
        response_time_ms = int((time.time() - response_start) * 1000)

        # Log AI response to database
        WidgetLogger.log_message(
            session_id=session_id,
            message_type='assistant',
            content=ai_response,
            bookstack_context=bookstack_context,
            response_time_ms=response_time_ms,
            llm_provider=provider_info.get('provider'),
            llm_model=provider_info.get('model')
        )

        # Add AI response to in-memory history
        WidgetSessionManager.add_message(session_id, 'assistant', ai_response)

        return {
            'success': True,
            'response': ai_response,
            'session_id': session_id,
            'timestamp': int(time.time()),
            'response_time_ms': response_time_ms
        }

    except Exception as e:
        logger.error(f"Error processing widget message: {str(e)}")
        return {
            'success': False,
            'error': 'Failed to process message',
            'details': str(e)
        }


def generate_widget_response(
    user_message: str,
    session_id: str,
    bookstack_context: Optional[Dict[str, Any]] = None
) -> tuple[str, Dict[str, Any]]:
    """Generate AI response for widget user

    Returns:
        tuple: (response_text, provider_info)
    """
    try:
        # Try Azure first (preferred), then Ollama as fallback
        provider = None

        # First try Azure OpenAI (preferred for production)
        try:
            provider = create_llm_provider('azure')
            if provider.is_available():
                logger.info("Using Azure provider for widget")
            else:
                provider = None
        except Exception as e:
            logger.debug(f"Azure not available: {e}")

        # If Azure not available, try Ollama as fallback (only if enabled)
        if not provider and ENABLE_OLLAMA:
            try:
                provider = create_llm_provider('ollama')
                if provider.is_available():
                    logger.info("Using Ollama provider for widget (ENABLE_OLLAMA_FALLBACK=true)")
                else:
                    provider = None
            except Exception as e:
                logger.debug(f"Ollama not available: {e}")
        elif not provider and not ENABLE_OLLAMA:
            logger.info("Ollama fallback disabled, Azure not available")
        
        # Last fallback: Error if no provider available
        if not provider:
            if ENABLE_OLLAMA:
                logger.error("No LLM provider available (Azure and Ollama both unreachable)")
                return "Sorry, no AI service is currently available. Please try again later.", {'provider': 'error', 'model': None}
            else:
                logger.error("Azure OpenAI not available, Ollama is disabled")
                return "Azure OpenAI is not available. Please check the configuration.", {'provider': 'error', 'model': None}
        
        # Get message history
        messages = WidgetSessionManager.get_messages(session_id)
        
        # Build context from BookStack if available
        combined_context = ""
        if bookstack_context:
            # Build detailed context hint
            context_parts = []

            # Extract page name from URL
            page_name = "Unknown page"
            book_name = "Unknown book"  # Initialize outside of if-block
            if bookstack_context.get('url'):
                url_parts = bookstack_context['url'].split('/')
                if 'page' in url_parts:
                    page_idx = url_parts.index('page')
                    if page_idx + 1 < len(url_parts):
                        page_name = url_parts[page_idx + 1].replace('-', ' ').title()

                # Extract book name from URL
                if 'books' in url_parts:
                    book_idx = url_parts.index('books')
                    if book_idx + 1 < len(url_parts):
                        book_name = url_parts[book_idx + 1].replace('-', ' ').title()

            context_parts.append(f"User is viewing the '{page_name}' page in the '{book_name}' book")

            if bookstack_context.get('title'):
                context_parts.append(f"Page title: {bookstack_context['title']}")

            if bookstack_context.get('page_content'):
                # Use the full transmitted content (up to 3000 chars)
                content_preview = bookstack_context['page_content']
                context_parts.append(f"Page content: {content_preview}")

            context_hint = ". ".join(context_parts)

            # Enhanced query with specific context
            enhanced_query = f"{user_message}\n\nBookStack Context: {context_hint}"

            # Build RAG context with page awareness (HYBRID: Page + BookStack + KB)
            combined_context = ChatContextBuilder.build_combined_context(enhanced_query, bookstack_context)
        else:
            # Standard RAG context without page awareness (BookStack + KB only)
            combined_context = ChatContextBuilder.build_combined_context(user_message, None)
        
        # Prepare messages for LLM
        llm_messages = []

        # Add context if available as system message
        if combined_context:
            llm_messages.append({
                'role': 'system',
                'content': f"Relevant context from knowledge base:\n{combined_context}"
            })

        # Add conversation history (last 10 messages for context window)
        for msg in messages[-10:]:
            if msg['role'] in ['user', 'assistant']:
                # For the current user message, enhance it with BookStack context if available
                if msg['role'] == 'user' and msg['content'] == user_message and bookstack_context:
                    # Enhance the user message with specific context
                    enhanced_content = f"{msg['content']}\n\n[Current page context: {context_hint}]"
                    llm_messages.append({
                        'role': msg['role'],
                        'content': enhanced_content
                    })
                else:
                    llm_messages.append({
                        'role': msg['role'],
                        'content': msg['content']
                    })
        
        # System prompt — configurable via CHATBOT_SYSTEM_PROMPT env var
        default_system_prompt = (
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
        widget_system_prompt = os.getenv('CHATBOT_SYSTEM_PROMPT', default_system_prompt)

        # Debug: Log what we're sending to the LLM
        logger.info(f"Widget LLM Request - System Prompt: {widget_system_prompt[:100]}...")
        logger.info(f"Widget LLM Request - Messages count: {len(llm_messages)}")
        for i, msg in enumerate(llm_messages):
            content_preview = msg['content'][:150] + "..." if len(msg['content']) > 150 else msg['content']
            logger.info(f"Widget LLM Message {i}: {msg['role']} - {content_preview}")

        # Generate response
        response = provider.chat(llm_messages, system_prompt=widget_system_prompt)

        # Prepare provider info for logging
        provider_info = {
            'provider': provider.name if hasattr(provider, 'name') else 'unknown',
            'model': getattr(provider, 'model', None) if hasattr(provider, 'model') else None
        }

        logger.info(f"Generated widget response using {provider_info['provider']} for session {session_id}")
        return response, provider_info

    except Exception as e:
        logger.error(f"Error generating widget response: {str(e)}")
        return "Sorry, I could not process your request. Please try again.", {'provider': 'error', 'model': None}