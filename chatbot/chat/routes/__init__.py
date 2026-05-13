"""Chat routes blueprint and submodule registration."""

from flask import Blueprint

# Blueprint must be created before importing route modules.
chat_bp = Blueprint('chat', __name__, template_folder='../templates')

# Importing the submodules registers their routes on the blueprint.
from .views import *
from .api import *

# Optional export routes (not always shipped).
try:
    from ..export.routes import *
except ImportError:
    pass

__all__ = ['chat_bp']