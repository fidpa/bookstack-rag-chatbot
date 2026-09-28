"""Chat routes blueprint and submodule registration."""

from .blueprint import chat_bp

# Importing the submodules registers their routes on the blueprint.
from . import api, views  # noqa: E402,F401

__all__ = ["chat_bp"]
