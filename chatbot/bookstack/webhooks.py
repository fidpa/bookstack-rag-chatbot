"""
BookStack Webhook Handler

Handles incoming webhooks from BookStack for real-time content updates.
"""

import os
import hmac
import hashlib
import logging
import threading
from collections import OrderedDict
from typing import Optional, Tuple
from flask import request, Blueprint, jsonify
from functools import wraps

from utils.rate_limiter import require_allowed_ip
from .webhook_worker import GiveUp, QueueFull, WebhookWorker

logger = logging.getLogger(__name__)

# Create webhook blueprint
webhook_bp = Blueprint("bookstack_webhook", __name__, url_prefix="/webhook")

# Configuration
WEBHOOK_SECRET = os.getenv("BOOKSTACK_WEBHOOK_SECRET", "")

# Seconds between receiving an event and reading BookStack back. BookStack sends
# create, move and sort events before its own transaction has committed (see
# webhook_worker.py), so a read inside the request sees the old state.
SYNC_DELAY_SECONDS = 2.0
# Further attempts (seconds after the previous one) while the item is not visible yet,
# or while BookStack does not answer
RETRY_DELAYS = (3.0, 6.0, 12.0)
# Only a new item can be invisible because BookStack has not committed it yet. For
# any other event an item that BookStack refuses (404) is deleted or hidden from the
# token's user, and asking again would only fill the log; those are retried only
# while BookStack cannot be reached.
CREATE_EVENTS = ("page_create", "chapter_create", "book_create")
# The recycle-bin event is sent before the restore itself happens and names no
# item, so the whole wiki is walked (without pruning) some seconds later.
RESTORE_DELAY_SECONDS = 5.0

worker = WebhookWorker()

# The URL each page was last reported under. A job retried while BookStack was down
# can run after a newer event for the same page (a move, a rename); it must not store
# the URL from its own, older payload. The page read API returns no URL of its own.
_LATEST_URL_LIMIT = 10000
_latest_url: "OrderedDict[Tuple[str, int], str]" = OrderedDict()
_latest_url_lock = threading.Lock()


def _remember_url(kind: str, item_id: int, url: Optional[str]) -> None:
    if kind != "page":
        return  # books and chapters take their URL from the API
    with _latest_url_lock:
        if not url:
            # The newest event names no URL: fall back to the permalink, not to an
            # older event's URL
            _latest_url.pop((kind, item_id), None)
            return
        _latest_url[(kind, item_id)] = url
        _latest_url.move_to_end((kind, item_id))
        while len(_latest_url) > _LATEST_URL_LIMIT:
            _latest_url.popitem(last=False)


def _current_url(kind: str, item_id: int, url: Optional[str]) -> Optional[str]:
    with _latest_url_lock:
        return _latest_url.get((kind, item_id), url if url else None)


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
    # Restoring from the recycle bin. The payload carries no item, only the restore URL.
    "recycle_bin_restore",
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


def _queue(event: str, label: str, task, delay: float, retry_delays=()):
    """Hand a sync to the worker and answer BookStack right away."""
    try:
        worker.submit(label, task, delay, retry_delays)
    except QueueFull:
        logger.error(f"Webhook queue is full, dropped {label}; run resync.py")
        return jsonify({"error": "Too many pending webhooks"}), 503
    return jsonify({"status": "queued", "event": event}), 202


def _sync_item(
    kind: str, item_id: int, url: Optional[str], published: bool, created: bool
) -> bool:
    """
    Index one page, chapter or book. True when it is done, False to try again.

    A page that BookStack reports as published but that reads back as a draft, and
    a chapter or book that cannot be loaded yet, are not visible until BookStack
    has committed; for a create event (`created`) the worker retries those. Any
    event is retried while BookStack does not answer, also when only a page inside
    a book or chapter could not be read; otherwise an item that cannot be read is
    given up on at once.
    """
    from .api_client import get_bookstack_client
    from .sync_service import ContentSyncService

    sync_service = ContentSyncService(get_bookstack_client())
    if kind == "page":
        url = _current_url(kind, item_id, url)
        loaded = sync_service.sync_page(item_id, url=url)
        done = loaded and (not published or sync_service.is_indexed("page", item_id))
    elif kind == "chapter":
        done = sync_service.sync_chapter(item_id)
    else:
        done = sync_service.sync_book(item_id)
    if sync_service.unreachable:
        return False
    if done or created:
        return done
    raise GiveUp(
        f"{kind} {item_id} could not be read or stored, see the error above. A 404 "
        "means it was deleted or is hidden from the API token's user, a 401 that "
        "BookStack refuses the token. If it belongs in the index, run "
        "resync.py --full-resync"
    )


def _walk_wiki() -> bool:
    """
    Add and update everything BookStack reports, without pruning.

    Done unless no book could be read at all (BookStack unreachable, token refused).
    Walking the whole wiki again because one item failed to load would hold up every
    other webhook for the length of a walk; the next full resync picks that item up.
    """
    from .api_client import get_bookstack_client
    from .sync_service import ContentSyncService

    stats = ContentSyncService(get_bookstack_client()).sync_all(prune=False)
    if stats["errors"] and stats["books"]:
        logger.warning(
            f"Recycle-bin walk finished, but {stats['errors']} item(s) failed to "
            "load; run resync.py --full-resync"
        )
    return bool(stats["books"]) or not stats["errors"]


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

        if event == "recycle_bin_restore":
            return _queue(event, event, _walk_wiki, RESTORE_DELAY_SECONDS, RETRY_DELAYS)

        # BookStack sends the affected item as `related_item`, with its parents'
        # ids alongside; the item's public URL is the top-level `url`.
        item = data.get("related_item") or {}
        item_id = item.get("id")
        if not item_id:
            logger.warning(f"Webhook {event} without related_item.id, ignored")
            return jsonify({"error": "related_item.id missing"}), 400

        kind = event.split("_", 1)[0]

        # Removing needs nothing from BookStack, so it happens right away.
        if event in ("page_delete", "chapter_delete", "book_delete"):
            sync_service = ContentSyncService(get_bookstack_client())
            remove = {
                "page_delete": sync_service.remove_page_from_index,
                # The chapter is gone, so the API cannot list its pages any more.
                # Remove them by the chapter_id recorded at index time.
                "chapter_delete": sync_service.remove_chapter_from_index,
                "book_delete": sync_service.remove_book_from_index,
            }[event]
            remove(item_id)
            # A sync job that read the item just before BookStack deleted it would
            # write it back after this. The same removal, queued behind that job,
            # takes it out again.
            try:
                worker.submit(
                    f"{event} #{item_id}", lambda: remove(item_id) or True, 0.0, ()
                )
            except QueueFull:
                # The removal above stands; only the guard against a write-back is lost
                logger.warning(
                    f"Webhook queue is full, {event} #{item_id} not re-checked"
                )
            return jsonify({"status": "processed", "event": event}), 200

        # Everything else reads BookStack back, which has to wait for its commit.
        published = not item.get("draft")
        url = data.get("url")
        _remember_url(kind, item_id, url)
        created = event in CREATE_EVENTS
        return _queue(
            event,
            f"{event} #{item_id}",
            lambda: _sync_item(kind, item_id, url, published, created),
            SYNC_DELAY_SECONDS,
            RETRY_DELAYS,
        )

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
