"""Server-rendered widget routes (used by templates/chat/widget.html)."""

import logging
from flask import render_template
from . import chat_bp

logger = logging.getLogger(__name__)


@chat_bp.route("/widget")
def widget():
    """Widget view for BookStack integration - no authentication required"""
    try:
        # Widget doesn't require login - it's embedded in BookStack
        # BookStack handles authentication
        return render_template("chat/widget.html")
    except Exception as e:
        logger.error(f"Error loading widget interface: {str(e)}")
        return f"Widget Error: {str(e)}", 500
