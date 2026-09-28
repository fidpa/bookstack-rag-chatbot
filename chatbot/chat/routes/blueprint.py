"""The chat blueprint, in its own module so route modules can import it."""

from flask import Blueprint

chat_bp = Blueprint("chat", __name__, template_folder="../templates")
