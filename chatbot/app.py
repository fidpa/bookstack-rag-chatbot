#!/usr/bin/env python
"""
BookStack RAG Chatbot - Flask application entry point.
"""

import logging
import os
from urllib.parse import urlsplit

from flask import Flask, jsonify, redirect, render_template, send_from_directory
from flask_cors import CORS

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv is optional outside the container

# Configure logging before the other application modules log anything
from config import Config, setup_logging  # noqa: E402

setup_logging()

from utils.rate_limiter import apply_proxy_fix  # noqa: E402
from version import __version__  # noqa: E402

logger = logging.getLogger(__name__)

# Browser origins BookStack is served from during local development
DEV_ORIGINS = [
    "http://localhost:6875",
    "http://127.0.0.1:6875",
    "http://[::1]:6875",
]


def allowed_origins() -> list:
    """Origins allowed to call the widget API: the development hosts plus the
    scheme://host[:port] of BOOKSTACK_EXTERNAL_URL."""
    origins = list(DEV_ORIGINS)
    external = os.getenv("BOOKSTACK_EXTERNAL_URL")
    if external:
        parts = urlsplit(external)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in origins:
            origins.append(origin)
    return origins


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config.from_object(Config)
    apply_proxy_fix(app)

    from startup_migrations import run_startup_migrations

    # A failed setup does not stop the app (so /health stays reachable), but
    # /health reports it, and with it the container's health check.
    app.config["SCHEMA_OK"] = run_startup_migrations()

    # The widget sends no cookies, so credentials stay off.
    CORS(
        app,
        resources={
            r"/chat/api/*": {
                "origins": allowed_origins(),
                "methods": ["POST", "OPTIONS"],
                "allow_headers": ["Content-Type", "X-Widget-Session", "Accept"],
                "max_age": 3600,
            }
        },
    )

    from chat import chat_bp
    from bookstack.webhooks import webhook_bp

    app.register_blueprint(chat_bp, url_prefix="/chat")
    app.register_blueprint(webhook_bp)  # url_prefix /webhook is set on the blueprint

    register_routes(app)
    return app


def register_routes(app: Flask):
    @app.route("/")
    def index():
        """The chatbot has no front page of its own; send visitors to the wiki."""
        return redirect(os.getenv("BOOKSTACK_EXTERNAL_URL", "http://localhost:6875"))

    @app.route("/health")
    def health():
        if not app.config.get("SCHEMA_OK", True):
            return {
                "status": "unhealthy",
                "app": "chatbot",
                "version": __version__,
                "reason": "database setup failed, see the log",
            }, 503
        return {"status": "healthy", "app": "chatbot", "version": __version__}, 200

    @app.route("/debug")
    def debug():
        """Route list, only with FLASK_DEBUG=true."""
        if not app.debug:
            return jsonify({"error": "Not available in production"}), 403
        return jsonify({"routes": [str(rule) for rule in app.url_map.iter_rules()]})

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(
            app.static_folder, "favicon.svg", mimetype="image/svg+xml"
        )

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        return render_template("errors/500.html"), 500


app = create_app()

if __name__ == "__main__":
    # Local development only; the container runs waitress. Bound to loopback
    # because Flask's debugger executes code for whoever can reach it.
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8888")), debug=app.debug)
