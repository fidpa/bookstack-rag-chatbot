#!/usr/bin/env python
"""
BookStack RAG Chatbot - Flask application entry point.
"""

from flask import Flask, render_template, redirect, request, send_from_directory, jsonify
import os
import logging
import time

# Try to import Flask-CORS, but make it optional
try:
    from flask_cors import CORS
    CORS_AVAILABLE = True
except ImportError:
    CORS_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("Flask-CORS not available - CORS support disabled")

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, continue without it

# Configure logging mit Zeitzone (vor anderen Imports!)
from config import setup_logging
setup_logging()
logger = logging.getLogger(__name__)

def create_app():
    # Explicitly configure static folder
    app = Flask(__name__,
                static_folder='static',
                static_url_path='/static')

    # Load configuration
    from config import Config
    app.config.from_object(Config)

    # Run startup migrations
    try:
        from startup_migrations import check_and_run_migrations
        logger.info("Running startup migrations...")
        check_and_run_migrations()
        logger.info("Startup migrations completed")
    except Exception as e:
        logger.error(f"Startup migrations failed: {str(e)}")
        # Continue anyway - don't fail app startup
    
    # Configure CORS for BookStack widget integration if available
    if CORS_AVAILABLE:
        # Dynamic CORS origins based on environment
        def get_allowed_origins():
            origins = [
                "http://localhost:6875",
                "http://127.0.0.1:6875",
                "http://[::1]:6875",
                "http://bookstack:80",
                "http://host.docker.internal:6875",
                "http://bookstack.local:6875",
                "http://knowledgebot.local:8888"
            ]

            # Add Windows host IP if configured
            windows_ip = os.getenv('WINDOWS_HOST_IP')
            if windows_ip:
                origins.append(f"http://{windows_ip}:6875")
                logger.info(f"Added Windows host IP to CORS: {windows_ip}")

            # Add external URL if configured
            external_url = os.getenv('BOOKSTACK_EXTERNAL_URL')
            if external_url and external_url not in origins:
                origins.append(external_url)
                logger.info(f"Added external URL to CORS: {external_url}")

            return origins

        allowed_origins = get_allowed_origins()

        # Allow BookStack origins for widget integration
        # Using wildcard pattern to match all /chat/api/* endpoints
        CORS(app,
             resources={
                 r"/chat/api/*": {
                     "origins": allowed_origins,
                     "methods": ["GET", "POST", "OPTIONS"],
                     "allow_headers": ["Content-Type", "X-Widget-Session", "Accept", "Origin"],
                     "supports_credentials": True,
                     "expose_headers": ["Content-Type"],
                     "max_age": 3600
                 },
                 r"/chat/widget": {
                     "origins": allowed_origins,
                     "methods": ["GET", "OPTIONS"],
                     "supports_credentials": True
                 }
             })
        logger.info("CORS configured for BookStack widget integration")
    else:
        # Manual CORS headers as fallback
        def get_allowed_origins_fallback():
            origins = [
                'http://localhost:6875',
                'http://127.0.0.1:6875',
                'http://[::1]:6875',
                'http://bookstack:80',
                'http://host.docker.internal:6875',
                'http://bookstack.local:6875',
                'http://knowledgebot.local:8888'
            ]

            # Add Windows host IP if configured
            windows_ip = os.getenv('WINDOWS_HOST_IP')
            if windows_ip:
                origins.append(f"http://{windows_ip}:6875")

            # Add external URL if configured
            external_url = os.getenv('BOOKSTACK_EXTERNAL_URL')
            if external_url and external_url not in origins:
                origins.append(external_url)

            return origins

        @app.after_request
        def add_cors_headers(response):
            # Only add CORS headers for widget API endpoints
            if request.path.startswith('/chat/api/') or request.path == '/chat/widget':
                origin = request.headers.get('Origin')
                # Only allow specific origins (WSL-compatible)
                allowed_origins = get_allowed_origins_fallback()
                if origin in allowed_origins:
                    response.headers['Access-Control-Allow-Origin'] = origin
                    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
                    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Widget-Session, Accept'
                    response.headers['Access-Control-Allow-Credentials'] = 'true'
                    response.headers['Access-Control-Expose-Headers'] = 'Content-Type'
                    response.headers['Access-Control-Max-Age'] = '3600'
            return response
        logger.info("Manual CORS headers configured for BookStack widget")
    
    # Ensure data directory exists
    os.makedirs(os.path.dirname(app.config['DATABASE_PATH']), exist_ok=True)
    
    # No authentication needed - BookStack handles user auth
    # Widget operates without login requirements
    
    # Register blueprints
    register_blueprints(app)
    
    # Register main routes
    register_main_routes(app)
    
    # Register static file routes
    register_static_routes(app)
    
    # Register error handlers
    register_error_handlers(app)
    
    # Register context processors
    register_context_processors(app)
    
    # Register request handlers
    register_request_handlers(app)
    
    # Favicon route
    @app.route('/favicon.ico')
    def favicon():
        """Redirect favicon.ico to the SVG version"""
        return send_from_directory(app.static_folder, 'favicon.svg', mimetype='image/svg+xml')
    
    return app

def register_blueprints(app):
    """Register application blueprints"""
    
    # Auth blueprint removed - BookStack handles authentication
    
    # Chat blueprint
    try:
        from chat import chat_bp
        app.register_blueprint(chat_bp, url_prefix='/chat')
        logger.info("Chat blueprint registered")
    except ImportError:
        logger.warning("Chat blueprint not available yet")
    
    # BookStack Webhook blueprint - Widget-Integration
    try:
        from bookstack.webhooks import webhook_bp
        app.register_blueprint(webhook_bp)  # url_prefix is already set to /webhook in blueprint
        logger.info("BookStack Webhook blueprint registered")
    except ImportError:
        logger.warning("BookStack Webhook blueprint not available yet")

    # Widget-Only architecture: No admin blueprints needed

def register_main_routes(app):
    """Register main application routes"""

    @app.route('/')
    def index():
        """Home page - redirect to BookStack"""
        bookstack_url = os.getenv('BOOKSTACK_EXTERNAL_URL', 'http://localhost:6875')
        return redirect(bookstack_url)
    
    # Widget-Only: No admin functionality needed

    @app.route('/health')
    def health():
        """Health check endpoint"""
        return {'status': 'healthy', 'app': 'chatbot'}, 200

    @app.route('/debug')
    def debug():
        """Debug information — only available in development mode"""
        if not app.debug:
            return jsonify({'error': 'Not available in production'}), 403
        routes = [str(rule) for rule in app.url_map.iter_rules()]
        return jsonify({'routes': routes, 'debug': True})

def register_static_routes(app):
    """Register explicit static file routes as fallback"""
    
    @app.route('/static/<path:filename>')
    def serve_static(filename):
        """Serve static files explicitly"""
        logger.debug(f"Serving static file: {filename}")
        return send_from_directory(app.static_folder, filename)

def register_error_handlers(app):
    """Register error handlers"""
    
    @app.errorhandler(404)
    def not_found_error(error):
        # Log static file 404s for debugging
        if request.path.startswith('/static/'):
            logger.warning(f"Static file not found: {request.path}")
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        return render_template('errors/500.html'), 500

def register_context_processors(app):
    """Register template context processors"""
    
    @app.context_processor
    def inject_asset_version():
        """Inject asset version for cache busting"""
        if app.debug:
            # Development: Always fresh with current timestamp
            return {'asset_version': int(time.time())}
        else:
            # Production: Use app version or git commit hash
            # For now, use a static version that can be updated on deployment
            return {'asset_version': app.config.get('APP_VERSION', '0.1.1')}
    
    @app.context_processor
    def inject_globals():
        """Inject global template variables"""
        # Create dummy current_user for Widget-Only architecture
        class DummyUser:
            is_authenticated = False
            is_admin = False

        return {
            'app_name': 'BookStack RAG Chatbot',
            'current_year': time.strftime('%Y'),
            'current_user': DummyUser()
        }

def register_request_handlers(app):
    """Register request handlers"""
    
    @app.after_request
    def add_cache_headers(response):
        """Add cache headers for static files"""
        if request.path.startswith('/static/'):
            if not app.debug:
                # Production: Cache static files for 1 year
                # Version parameter will handle cache busting
                response.headers['Cache-Control'] = 'public, max-age=31536000'
            else:
                # Development: No cache
                response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                response.headers['Pragma'] = 'no-cache'
                response.headers['Expires'] = '0'
        return response

# Create app instance
app = create_app()

if __name__ == '__main__':
    # Try different ports until one works
    for port in [8888, 8893, 8894, 8895]:
        try:
            print("=" * 50)
            print("BookStack RAG Chatbot Starting")
            print("=" * 50)
            print(f"URL: http://localhost:{port}")
            print(f"Health: http://localhost:{port}/health")
            print(f"Widget: http://localhost:{port}/chat/widget")
            print("=" * 50)
            print(f"Trying port {port}...")
            app.run(debug=True, port=port, host='0.0.0.0')
            break
        except OSError as e:
            print(f"Port {port} error: {e}")
            continue