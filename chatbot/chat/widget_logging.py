"""
Widget Chat Logging Service
Handles persistent logging of widget chat interactions to database
"""

import logging
import sqlite3
import time
import re
from typing import Dict, Any, Optional, List, Tuple
from flask import request
from utils.database import get_db_path
from utils.timezone_helpers import now_local, format_for_database, format_time_local

logger = logging.getLogger(__name__)


class WidgetLogger:
    """
    Service for logging widget chat interactions to database
    Provides analytics and search capabilities for widget usage
    """

    @staticmethod
    def log_message(
        session_id: str,
        message_type: str,
        content: str,
        bookstack_context: Optional[Dict[str, Any]] = None,
        response_time_ms: Optional[int] = None,
        llm_provider: Optional[str] = None,
        llm_model: Optional[str] = None
    ) -> bool:
        """
        Log a widget chat message to database

        Args:
            session_id: Widget session ID
            message_type: 'user' or 'assistant'
            content: Message content
            bookstack_context: BookStack page context
            response_time_ms: Response time in milliseconds
            llm_provider: LLM provider used (ollama, azure, mock)
            llm_model: Specific model used

        Returns:
            bool: Success status
        """
        try:
            db_path = get_db_path()

            # Extract BookStack context
            bs_page_id = None
            bs_page_title = None
            bs_page_url = None
            bs_book_id = None
            bs_book_title = None

            if bookstack_context:
                bs_page_id = bookstack_context.get('page_id')
                bs_page_title = bookstack_context.get('title')
                bs_page_url = bookstack_context.get('url')
                bs_book_id = bookstack_context.get('book_id')
                bs_book_title = bookstack_context.get('book_title')

            # Get request info
            ip_address = None
            user_agent = None
            try:
                if request:
                    ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR'))
                    user_agent = request.environ.get('HTTP_USER_AGENT', '')[:500]  # Truncate long user agents
            except RuntimeError:
                # Outside request context
                pass

            # Calculate word count
            word_count = len(content.split()) if content else 0

            # Detect language (simple heuristic)
            language = WidgetLogger._detect_language(content)

            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()

                # Insert log entry mit expliziter lokaler Zeitzone
                timestamp = format_for_database()
                cursor.execute("""
                    INSERT INTO widget_chat_logs (
                        session_id, message_type, content,
                        bookstack_page_id, bookstack_page_title, bookstack_page_url,
                        bookstack_book_id, bookstack_book_title,
                        response_time_ms, llm_provider, llm_model,
                        ip_address, user_agent, word_count, language, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    session_id, message_type, content,
                    bs_page_id, bs_page_title, bs_page_url,
                    bs_book_id, bs_book_title,
                    response_time_ms, llm_provider, llm_model,
                    ip_address, user_agent, word_count, language, timestamp
                ))

                log_id = cursor.lastrowid

                # Update FTS index for searchability
                if content and message_type == 'user':  # Only index user questions
                    try:
                        cursor.execute("""
                            INSERT INTO widget_chat_fts (log_id, content)
                            VALUES (?, ?)
                        """, (log_id, content))
                    except Exception as fts_error:
                        logger.warning(f"Failed to update FTS index: {fts_error}")

                conn.commit()

                logger.debug(f"Logged widget message: {message_type} from session {session_id[:8]}...")
                return True

        except Exception as e:
            logger.error(f"Failed to log widget message: {str(e)}")
            return False

    @staticmethod
    def format_log_timestamps(logs: List[Tuple]) -> List[Tuple]:
        """
        Formatiert Timestamps in Log-Einträgen für einheitliche Anzeige

        Args:
            logs: Liste von Log-Tupeln mit Timestamp an Position -1

        Returns:
            List[Tuple]: Logs mit formatiertem Timestamp
        """
        formatted_logs = []
        for log in logs:
            log_list = list(log)
            if log_list and len(log_list) > 0:
                # Assume timestamp ist das letzte Element
                timestamp = log_list[-1]
                if timestamp:
                    log_list[-1] = format_time_local(timestamp)
            formatted_logs.append(tuple(log_list))
        return formatted_logs

    @staticmethod
    def get_session_stats(session_id: str) -> Dict[str, Any]:
        """Get statistics for a specific widget session"""
        try:
            db_path = get_db_path()

            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # Get basic session info
                cursor.execute("""
                    SELECT
                        COUNT(*) as total_messages,
                        COUNT(CASE WHEN message_type = 'user' THEN 1 END) as user_messages,
                        COUNT(CASE WHEN message_type = 'assistant' THEN 1 END) as assistant_messages,
                        MIN(timestamp) as session_start,
                        MAX(timestamp) as session_end,
                        AVG(CASE WHEN message_type = 'assistant' THEN response_time_ms END) as avg_response_time,
                        COUNT(DISTINCT bookstack_page_id) as pages_visited
                    FROM widget_chat_logs
                    WHERE session_id = ?
                """, (session_id,))

                row = cursor.fetchone()
                return dict(row) if row else {}

        except Exception as e:
            logger.error(f"Failed to get session stats: {str(e)}")
            return {}

    @staticmethod
    def get_frequent_questions(limit: int = 20) -> List[Dict[str, Any]]:
        """Get most frequently asked questions"""
        try:
            db_path = get_db_path()

            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT * FROM widget_frequent_questions
                    LIMIT ?
                """, (limit,))

                return [dict(row) for row in cursor.fetchall()]

        except Exception as e:
            logger.error(f"Failed to get frequent questions: {str(e)}")
            return []

    @staticmethod
    def get_page_analytics(limit: int = 20) -> List[Dict[str, Any]]:
        """Get analytics for BookStack pages with widget interaction"""
        try:
            db_path = get_db_path()

            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT * FROM widget_page_analytics
                    LIMIT ?
                """, (limit,))

                return [dict(row) for row in cursor.fetchall()]

        except Exception as e:
            logger.error(f"Failed to get page analytics: {str(e)}")
            return []

    @staticmethod
    def search_similar_questions(query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for similar questions using FTS5"""
        try:
            db_path = get_db_path()

            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # Use FTS5 MATCH syntax
                search_query = query.replace("'", "''")  # Escape quotes

                cursor.execute("""
                    SELECT l.content, l.timestamp, l.bookstack_page_title,
                           f.rank
                    FROM widget_chat_fts f
                    JOIN widget_chat_logs l ON f.log_id = l.id
                    WHERE f.content MATCH ?
                    ORDER BY f.rank
                    LIMIT ?
                """, (search_query, limit))

                return [dict(row) for row in cursor.fetchall()]

        except Exception as e:
            logger.error(f"Failed to search similar questions: {str(e)}")
            return []

    @staticmethod
    def get_usage_stats(days: int = 30) -> Dict[str, Any]:
        """Get overall widget usage statistics"""
        try:
            db_path = get_db_path()

            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # Get stats for last N days
                cursor.execute("""
                    SELECT
                        COUNT(*) as total_messages,
                        COUNT(DISTINCT session_id) as unique_sessions,
                        COUNT(CASE WHEN message_type = 'user' THEN 1 END) as user_questions,
                        COUNT(CASE WHEN message_type = 'assistant' THEN 1 END) as assistant_responses,
                        AVG(CASE WHEN message_type = 'assistant' THEN response_time_ms END) as avg_response_time,
                        COUNT(DISTINCT bookstack_page_id) as pages_with_interaction,
                        MIN(timestamp) as earliest_message,
                        MAX(timestamp) as latest_message
                    FROM widget_chat_logs
                    WHERE timestamp >= datetime('now', '-' || ? || ' days')
                """, (days,))

                stats = dict(cursor.fetchone()) if cursor.fetchone() else {}

                # Get provider distribution
                cursor.execute("""
                    SELECT llm_provider, COUNT(*) as count
                    FROM widget_chat_logs
                    WHERE message_type = 'assistant'
                    AND timestamp >= datetime('now', '-' || ? || ' days')
                    AND llm_provider IS NOT NULL
                    GROUP BY llm_provider
                    ORDER BY count DESC
                """, (days,))

                stats['provider_distribution'] = [dict(row) for row in cursor.fetchall()]

                return stats

        except Exception as e:
            logger.error(f"Failed to get usage stats: {str(e)}")
            return {}

    @staticmethod
    def _detect_language(content: str) -> str:
        """Simple language detection based on common words"""
        if not content:
            return 'de'

        content_lower = content.lower()

        # German indicators
        german_words = ['der', 'die', 'das', 'und', 'ist', 'ich', 'wie', 'was', 'kann', 'haben']
        # English indicators
        english_words = ['the', 'and', 'is', 'can', 'have', 'how', 'what', 'this', 'that', 'with']

        german_count = sum(1 for word in german_words if word in content_lower)
        english_count = sum(1 for word in english_words if word in content_lower)

        return 'en' if english_count > german_count else 'de'

    @staticmethod
    def cleanup_old_logs(days_to_keep: int = 90) -> int:
        """
        Delete old widget logs to manage database size

        Args:
            days_to_keep: Number of days to retain logs

        Returns:
            int: Number of deleted records
        """
        try:
            db_path = get_db_path()

            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()

                # Delete old logs
                cursor.execute("""
                    DELETE FROM widget_chat_logs
                    WHERE timestamp < datetime('now', '-' || ? || ' days')
                """, (days_to_keep,))

                deleted_count = cursor.rowcount

                # Clean up FTS index (SQLite will handle this automatically)
                cursor.execute("INSERT INTO widget_chat_fts(widget_chat_fts) VALUES('optimize')")

                conn.commit()

                logger.info(f"Cleaned up {deleted_count} old widget log entries (older than {days_to_keep} days)")
                return deleted_count

        except Exception as e:
            logger.error(f"Failed to cleanup old logs: {str(e)}")
            return 0