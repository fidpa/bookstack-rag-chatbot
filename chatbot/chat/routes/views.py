"""Server-rendered widget routes (used by templates/chat/widget.html)."""

import logging
import os
from urllib.parse import urlsplit

from flask import render_template
from .blueprint import chat_bp

logger = logging.getLogger(__name__)


def _bookstack_origin() -> str:
    """scheme://host[:port] of BOOKSTACK_EXTERNAL_URL, the only origin allowed
    to post page context into the widget frame."""
    parts = urlsplit(os.getenv("BOOKSTACK_EXTERNAL_URL", "http://localhost:6875"))
    return f"{parts.scheme}://{parts.netloc}"


@chat_bp.route("/widget")
def widget():
    """Standalone chat page; no authentication, BookStack handles that."""
    return render_template("chat/widget.html", bookstack_origin=_bookstack_origin())
