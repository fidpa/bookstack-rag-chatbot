"""
BookStack Webhook Handler

Handles incoming webhooks from BookStack for real-time content updates.
"""

import os
import hmac
import hashlib
import logging
from flask import request, Blueprint, jsonify
from functools import wraps

from utils.rate_limiter import require_allowed_ip

logger = logging.getLogger(__name__)

# Create webhook blueprint
webhook_bp = Blueprint("bookstack_webhook", __name__, url_prefix="/webhook")

# Configuration
WEBHOOK_SECRET = os.getenv("BOOKSTACK_WEBHOOK_SECRET", "")

# Bookshelf events are deliberately absent. A shelf groups books and holds no
# indexable content of its own, and since bookshelf_* starts with the same
# letters as book_*, the book branch of bookstack_webhook() would swallow them
# and report them as processed without touching the index.
RELEVANT_EVENTS = [
    # Page events
    "page_create",
    "page_update",
    "page_delete",
    "page_move",
    "page_restore",
    # Chapter events
    "chapter_create",
    "chapter_update",
    "chapter_delete",
    "chapter_move",
    # Book events
    "book_create",
    "book_update",
    "book_delete",
    "book_sort",
]


def verify_hmac_signature(secret: str, payload: bytes, signature: str) -> bool:
    """
    Verify HMAC signature from BookStack webhook

    Args:
        secret: Webhook secret key
        payload: Request body bytes
        signature: Signature from X-BookStack-Signature header

    Returns:
        True if signature is valid
    """
    if not secret or not signature:
        return False

    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    return hmac.compare_digest(signature, expected)


def require_webhook_auth(f):
    """Verify the HMAC signature when a webhook secret is configured.

    Behaviour:
      * BOOKSTACK_WEBHOOK_SECRET unset  → request passes through (BookStack v25.07
        does not sign payloads; authenticity relies on ALLOWED_VPN_IPS).
      * BOOKSTACK_WEBHOOK_SECRET set    → header X-BookStack-Signature is required
        and verified. Set this only against a BookStack build that signs
        webhooks (custom plugin or future release).
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not WEBHOOK_SECRET:
            return f(*args, **kwargs)

        signature = request.headers.get("X-BookStack-Signature", "")
        if not verify_hmac_signature(WEBHOOK_SECRET, request.data, signature):
            logger.warning(f"Invalid webhook signature from {request.remote_addr}")
            return jsonify({"error": "Unauthorized"}), 401

        return f(*args, **kwargs)

    return decorated_function


@webhook_bp.route("/bookstack", methods=["POST"])
@require_allowed_ip
@require_webhook_auth
def bookstack_webhook():
    """
    Main webhook endpoint for BookStack events

    Handles content updates and triggers re-indexing as needed.
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "No data provided"}), 400

        event = data.get("event")

        # Quick exit for irrelevant events
        if event not in RELEVANT_EVENTS:
            logger.debug(f"Ignoring event: {event}")
            return jsonify({"status": "ignored"}), 200

        # Process relevant events
        logger.info(f"Processing BookStack event: {event}")

        # Import here to avoid circular imports
        from .api_client import get_bookstack_client
        from .sync_service import ContentSyncService

        client = get_bookstack_client()
        sync_service = ContentSyncService(client)

        # BookStack sends the affected item as `related_item`, with its parents'
        # ids alongside; the item's public URL is the top-level `url`.
        item = data.get("related_item") or {}
        item_id = item.get("id")
        if not item_id:
            logger.warning(f"Webhook {event} without related_item.id, ignored")
            return jsonify({"error": "related_item.id missing"}), 400

        kind = event.split("_", 1)[0]
        client.invalidate_cache(f"{kind}_{item_id}")
        # A book sync reads its contents list from the cache; drop the parents so
        # the next one sees the change.
        for parent in ("book", "chapter"):
            if item.get(f"{parent}_id"):
                client.invalidate_cache(f"{parent}_{item[f'{parent}_id']}")

        if event == "page_delete":
            sync_service.remove_page_from_index(item_id)
        elif event == "chapter_delete":
            # The chapter is gone, so the API cannot list its pages any more.
            # Remove them by the chapter_id recorded at index time.
            sync_service.remove_chapter_from_index(item_id)
        elif event == "book_delete":
            sync_service.remove_book_from_index(item_id)
        elif kind == "page":
            sync_service.sync_page(item_id, url=data.get("url"))
        elif kind == "chapter":
            sync_service.sync_chapter(item_id)
        else:
            sync_service.sync_book(item_id)

        return jsonify({"status": "processed", "event": event}), 200

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return jsonify({"error": "Internal error"}), 500


@webhook_bp.route("/bookstack/test", methods=["GET", "POST"])
def test_webhook():
    """
    Test endpoint to verify webhook configuration

    Can be used to test connectivity without authentication.
    """
    if request.method == "GET":
        return jsonify(
            {
                "status": "ready",
                "message": "Webhook endpoint is configured",
                "accepts": RELEVANT_EVENTS,
            }
        )

    # POST for testing webhook processing
    return jsonify(
        {
            "status": "test_received",
            "method": request.method,
            "has_signature": "X-BookStack-Signature" in request.headers,
        }
    )


def setup_webhook_routes(app):
    """
    Register webhook blueprint with Flask app

    Args:
        app: Flask application instance
    """
    app.register_blueprint(webhook_bp)
    logger.info("BookStack webhook routes registered at /webhook/bookstack")
