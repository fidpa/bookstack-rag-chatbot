"""Widget API routes — endpoints called by the BookStack-embedded JS widget."""

import logging
from flask import request, jsonify
from . import chat_bp
from utils.rate_limiter import rate_limiter, require_allowed_ip

logger = logging.getLogger(__name__)


@chat_bp.route("/api/widget", methods=["POST", "OPTIONS"])
@require_allowed_ip
@rate_limiter.ip_limit()
def widget_chat():
    """
    Main chat endpoint for BookStack widget
    No authentication required - BookStack handles user auth
    Uses session-based tracking for conversation history
    """
    # Handle preflight OPTIONS request for CORS
    if request.method == "OPTIONS":
        return "", 204

    try:
        # Get request data
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data received"}), 400

        message = data.get("message", "").strip()
        session_id = data.get("session_id")
        bookstack_context = data.get("bookstack_context", {})

        if not message:
            return jsonify({"success": False, "error": "Message cannot be empty"}), 400

        # Import widget service
        from ..widget_service import process_widget_message

        # Process message and generate response
        result = process_widget_message(
            message=message, session_id=session_id, bookstack_context=bookstack_context
        )

        if result["success"]:
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        logger.error(f"Widget chat endpoint error: {str(e)}")
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Failed to process chat message",
                    "details": str(e),
                }
            ),
            500,
        )


@chat_bp.route("/api/echo", methods=["POST", "OPTIONS"])
@require_allowed_ip
def widget_echo():
    """Lightweight connectivity probe used by the widget at page load.

    Does not invoke the LLM and is not rate-limited. Returns the posted
    payload (if any) so the widget can verify CORS + reverse-proxy plumbing.
    """
    if request.method == "OPTIONS":
        return "", 204

    payload = request.get_json(silent=True) or {}
    return (
        jsonify(
            {
                "success": True,
                "echo": payload,
                "session": request.headers.get("X-Widget-Session", ""),
            }
        ),
        200,
    )
