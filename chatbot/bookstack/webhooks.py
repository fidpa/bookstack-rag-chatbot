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
webhook_bp = Blueprint('bookstack_webhook', __name__, url_prefix='/webhook')

# Configuration
WEBHOOK_SECRET = os.getenv('BOOKSTACK_WEBHOOK_SECRET', '')
RELEVANT_EVENTS = [
    # Page events
    'page_create', 'page_update', 'page_delete', 'page_move', 'page_restore',
    # Chapter events
    'chapter_create', 'chapter_update', 'chapter_delete', 'chapter_move',
    # Book events
    'book_create', 'book_update', 'book_delete', 'book_sort',
    # Bookshelf events (optional)
    'bookshelf_create', 'bookshelf_update', 'bookshelf_delete'
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
        
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
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

        signature = request.headers.get('X-BookStack-Signature', '')
        if not verify_hmac_signature(WEBHOOK_SECRET, request.data, signature):
            logger.warning(f"Invalid webhook signature from {request.remote_addr}")
            return jsonify({'error': 'Unauthorized'}), 401

        return f(*args, **kwargs)
    return decorated_function


@webhook_bp.route('/bookstack', methods=['POST'])
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
            return jsonify({'error': 'No data provided'}), 400
        
        event = data.get('event')
        
        # Quick exit for irrelevant events
        if event not in RELEVANT_EVENTS:
            logger.debug(f"Ignoring event: {event}")
            return jsonify({'status': 'ignored'}), 200
        
        # Process relevant events
        logger.info(f"Processing BookStack event: {event}")
        
        # Import here to avoid circular imports
        from .api_client import get_bookstack_client
        from .sync_service import ContentSyncService
        
        client = get_bookstack_client()
        sync_service = ContentSyncService(client)
        
        # Handle different event types
        if 'page' in event:
            page_id = data.get('related', {}).get('page', {}).get('id')
            if page_id:
                # Invalidate cache for this page
                client.invalidate_cache(f'page_{page_id}')
                
                if event == 'page_delete':
                    # Remove from index
                    sync_service.remove_page_from_index(page_id)
                else:
                    # Re-index the page
                    sync_service.sync_page(page_id)
                    
        elif 'chapter' in event:
            chapter_id = data.get('related', {}).get('chapter', {}).get('id')
            if chapter_id:
                client.invalidate_cache(f'chapter_{chapter_id}')
                # Re-index all pages in chapter
                sync_service.sync_chapter(chapter_id)
                
        elif 'book' in event:
            book_id = data.get('related', {}).get('book', {}).get('id')
            if book_id:
                client.invalidate_cache(f'book_{book_id}')
                # Re-index entire book
                sync_service.sync_book(book_id)
        
        return jsonify({
            'status': 'processed',
            'event': event
        }), 200
        
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return jsonify({'error': 'Internal error'}), 500


@webhook_bp.route('/bookstack/test', methods=['GET', 'POST'])
def test_webhook():
    """
    Test endpoint to verify webhook configuration
    
    Can be used to test connectivity without authentication.
    """
    if request.method == 'GET':
        return jsonify({
            'status': 'ready',
            'message': 'Webhook endpoint is configured',
            'accepts': RELEVANT_EVENTS
        })
    
    # POST for testing webhook processing
    return jsonify({
        'status': 'test_received',
        'method': request.method,
        'has_signature': 'X-BookStack-Signature' in request.headers
    })


def setup_webhook_routes(app):
    """
    Register webhook blueprint with Flask app
    
    Args:
        app: Flask application instance
    """
    app.register_blueprint(webhook_bp)
    logger.info("BookStack webhook routes registered at /webhook/bookstack")