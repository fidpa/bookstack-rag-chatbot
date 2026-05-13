"""
Rate limiting and IP-based access control for chatbot endpoints.

Two mechanisms:
- `require_allowed_ip`  : enforces the ALLOWED_VPN_IPS allow-list (CIDRs).
- `RateLimiter.ip_limit`: sliding-window per-IP request cap, configurable
                          via RATE_LIMIT_PER_MINUTE.
"""

import ipaddress
import logging
import os
import time
from functools import wraps

from flask import jsonify, request, session

logger = logging.getLogger(__name__)


def _client_ip() -> str:
    """Return the originating client IP, honouring a single X-Forwarded-For hop.

    SECURITY.md tells operators to strip X-Forwarded-For at the edge proxy when
    the proxy is reachable from the public internet; this helper trusts the
    first hop only.
    """
    forwarded = request.environ.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.environ.get('REMOTE_ADDR', '')


def _parse_allowed_cidrs(raw: str):
    """Parse a comma-separated CIDR list. Returns [] for empty/invalid input."""
    if not raw:
        return []
    networks = []
    for entry in raw.split(','):
        cidr = entry.strip()
        if not cidr:
            continue
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            logger.warning(f"Ignoring invalid CIDR in ALLOWED_VPN_IPS: {cidr!r}")
    return networks


def require_allowed_ip(f):
    """Reject requests from IPs not on the ALLOWED_VPN_IPS allow-list.

    Bypassed if IP_ACCESS_CONTROL is set to anything other than 'true'
    (case-insensitive). An empty ALLOWED_VPN_IPS means 'allow all' and is
    logged once per process startup as a warning.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        enabled = os.getenv('IP_ACCESS_CONTROL', 'true').strip().lower() == 'true'
        if not enabled:
            return f(*args, **kwargs)

        raw_cidrs = os.getenv('ALLOWED_VPN_IPS', '').strip()
        if not raw_cidrs:
            if not getattr(require_allowed_ip, '_warned_empty', False):
                logger.warning(
                    "IP_ACCESS_CONTROL=true but ALLOWED_VPN_IPS is empty "
                    "- allowing all source IPs."
                )
                require_allowed_ip._warned_empty = True
            return f(*args, **kwargs)

        networks = _parse_allowed_cidrs(raw_cidrs)
        if not networks:
            logger.error(
                "ALLOWED_VPN_IPS is set but contains no valid CIDRs "
                "- denying all requests."
            )
            return jsonify({'success': False, 'error': 'Access denied'}), 403

        client_ip = _client_ip()
        try:
            addr = ipaddress.ip_address(client_ip)
        except ValueError:
            logger.warning(f"Rejecting request with unparseable source IP {client_ip!r}")
            return jsonify({'success': False, 'error': 'Access denied'}), 403

        if not any(addr in net for net in networks):
            logger.warning(f"Denied {client_ip} (not in ALLOWED_VPN_IPS)")
            return jsonify({'success': False, 'error': 'Access denied'}), 403

        return f(*args, **kwargs)
    return decorated


class RateLimiter:
    """Simple in-memory rate limiter"""
    
    def __init__(self):
        self.requests = {}
    
    def limit(self, max_requests=10, window=60):
        """
        Decorator to rate limit endpoints by IP address.

        Args:
            max_requests: Maximum number of requests allowed
            window: Time window in seconds
        """
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                client_ip = _client_ip() or 'unknown'
                key = f"{client_ip}:{f.__name__}"
                now = time.time()

                # Clean old entries
                if key in self.requests:
                    self.requests[key] = [
                        req for req in self.requests[key]
                        if req > now - window
                    ]
                else:
                    self.requests[key] = []

                # Check limit
                if len(self.requests[key]) >= max_requests:
                    remaining_time = int(window - (now - self.requests[key][0]))
                    logger.warning(f"Rate limit exceeded for IP {client_ip} on {f.__name__}")

                    return jsonify({
                        'success': False,
                        'error': f'Too many requests. Please wait {remaining_time} seconds.',
                        'retry_after': remaining_time
                    }), 429

                # Add request
                self.requests[key].append(now)

                # Execute function
                return f(*args, **kwargs)

            return decorated_function

        return decorator

    def ip_limit(self, max_requests=None, window=60):
        """Per-IP sliding-window rate limit driven by RATE_LIMIT_PER_MINUTE.

        When ``max_requests`` is None, the value is read from the
        RATE_LIMIT_PER_MINUTE env var at decoration time (default: 30).
        """
        if max_requests is None:
            try:
                max_requests = int(os.getenv('RATE_LIMIT_PER_MINUTE', '30'))
            except ValueError:
                logger.warning("RATE_LIMIT_PER_MINUTE is not an integer, using 30")
                max_requests = 30

        return self.limit(max_requests=max_requests, window=window)

    def authenticated_limit(self, max_requests=10, window=60):
        """
        Rate limit decorator for widget endpoints (no authentication required)
        Uses session-based tracking for anonymous widget users
        """
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                # Use session ID as identifier for widget users
                session_key = 'rate_limit_session_id'
                if session_key not in session:
                    # Create a unique session identifier for rate limiting
                    import uuid
                    session[session_key] = str(uuid.uuid4())

                session_id = session[session_key]
                key = f"session_{session_id}:{f.__name__}"
                now = time.time()

                # Clean old entries
                if key in self.requests:
                    self.requests[key] = [
                        req for req in self.requests[key]
                        if req > now - window
                    ]
                else:
                    self.requests[key] = []

                # Check limit
                if len(self.requests[key]) >= max_requests:
                    remaining_time = int(window - (now - self.requests[key][0]))
                    logger.warning(f"Rate limit exceeded for session {session_id[:8]} on {f.__name__}")

                    return jsonify({
                        'success': False,
                        'error': f'Zu viele Anfragen. Bitte warten Sie {remaining_time} Sekunden.',
                        'retry_after': remaining_time
                    }), 429

                # Add request
                self.requests[key].append(now)

                # Execute function
                return f(*args, **kwargs)

            return decorated_function
        return decorator
    
    def reset(self, session_id=None, endpoint=None):
        """Reset rate limits for testing or admin purposes"""
        if session_id and endpoint:
            key = f"session_{session_id}:{endpoint}"
            if key in self.requests:
                del self.requests[key]
        elif session_id:
            # Reset all endpoints for session
            keys_to_delete = [k for k in self.requests.keys() if k.startswith(f"session_{session_id}:")]
            for key in keys_to_delete:
                del self.requests[key]
        else:
            # Reset all
            self.requests.clear()


# Global rate limiter instance
rate_limiter = RateLimiter()