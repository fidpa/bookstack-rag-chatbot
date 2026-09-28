"""
Rate limiting and IP-based access control for chatbot endpoints.

Two mechanisms:
- `require_allowed_ip`  : enforces the ALLOWED_VPN_IPS allow-list (CIDRs).
- `RateLimiter.ip_limit`: sliding-window per-IP request cap, configurable
                          via RATE_LIMIT_PER_MINUTE.

Both key on the client address Flask reports as request.remote_addr. Behind a
reverse proxy that is the proxy's address unless TRUSTED_PROXY_HOPS says how
many proxies to look through (see apply_proxy_fix).
"""

import ipaddress
import logging
import os
import threading
import time
from functools import wraps

from flask import jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix

logger = logging.getLogger(__name__)


def trusted_proxy_hops() -> int:
    """TRUSTED_PROXY_HOPS as a non-negative int (default 0)."""
    try:
        return max(0, int(os.getenv("TRUSTED_PROXY_HOPS", "0")))
    except ValueError:
        logger.warning("TRUSTED_PROXY_HOPS is not an integer, using 0")
        return 0


def apply_proxy_fix(app):
    """
    Take the client address from X-Forwarded-For when behind trusted proxies.

    With TRUSTED_PROXY_HOPS=N, ProxyFix uses the N-th entry from the *right* of
    X-Forwarded-For, which is the one the outermost trusted proxy appended. The
    entries to its left come from the client and are ignored, so a forged
    header no longer changes the address. With 0 (the default) the header is
    ignored entirely: set it only when every request passes through the proxy,
    otherwise a client talking to port 8888 directly could forge it.
    """
    hops = trusted_proxy_hops()
    if hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops)
        logger.info(f"Trusting {hops} proxy hop(s) for the client address")


def _client_ip() -> str:
    return request.remote_addr or ""


def _parse_allowed_cidrs(raw: str):
    """Parse a comma-separated CIDR list. Returns [] for empty/invalid input."""
    if not raw:
        return []
    networks = []
    for entry in raw.split(","):
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
    logged as a warning on the first guarded request.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        enabled = os.getenv("IP_ACCESS_CONTROL", "true").strip().lower() == "true"
        if not enabled:
            return f(*args, **kwargs)

        raw_cidrs = os.getenv("ALLOWED_VPN_IPS", "").strip()
        if not raw_cidrs:
            if not getattr(require_allowed_ip, "_warned_empty", False):
                logger.warning(
                    "IP_ACCESS_CONTROL=true but ALLOWED_VPN_IPS is empty "
                    "- allowing all source IPs."
                )
                require_allowed_ip._warned_empty = True  # type: ignore[attr-defined]
            return f(*args, **kwargs)

        networks = _parse_allowed_cidrs(raw_cidrs)
        if not networks:
            logger.error(
                "ALLOWED_VPN_IPS is set but contains no valid CIDRs "
                "- denying all requests."
            )
            return jsonify({"success": False, "error": "Access denied"}), 403

        client_ip = _client_ip()
        try:
            addr = ipaddress.ip_address(client_ip)
        except ValueError:
            logger.warning(
                f"Rejecting request with unparseable source IP {client_ip!r}"
            )
            return jsonify({"success": False, "error": "Access denied"}), 403

        if not any(addr in net for net in networks):
            logger.warning(f"Denied {client_ip} (not in ALLOWED_VPN_IPS)")
            return jsonify({"success": False, "error": "Access denied"}), 403

        return f(*args, **kwargs)

    return decorated


class RateLimiter:
    """In-memory sliding-window rate limiter, shared by all waitress threads."""

    #: Seconds between sweeps that drop keys with no recent requests
    SWEEP_INTERVAL = 60

    def __init__(self):
        self.requests = {}
        self._lock = threading.Lock()
        self._last_sweep = time.time()

    def _sweep(self, now: float, window: int):
        """Forget clients without requests in the window, so memory stays bounded."""
        if now - self._last_sweep < self.SWEEP_INTERVAL:
            return
        self._last_sweep = now
        for key in [
            k for k, v in self.requests.items() if not v or v[-1] <= now - window
        ]:
            del self.requests[key]

    def clear(self):
        """Forget all recorded requests."""
        with self._lock:
            self.requests.clear()

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
                client_ip = _client_ip() or "unknown"
                key = f"{client_ip}:{f.__name__}"
                now = time.time()

                with self._lock:
                    self._sweep(now, window)
                    recent = [t for t in self.requests.get(key, []) if t > now - window]
                    if len(recent) >= max_requests:
                        remaining_time = max(1, int(window - (now - recent[0])))
                        self.requests[key] = recent
                        limited = True
                    else:
                        recent.append(now)
                        self.requests[key] = recent
                        limited = False

                if limited:
                    logger.warning(
                        f"Rate limit exceeded for IP {client_ip} on {f.__name__}"
                    )
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": f"Too many requests. Please wait {remaining_time} seconds.",
                                "retry_after": remaining_time,
                            }
                        ),
                        429,
                    )

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
                max_requests = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
            except ValueError:
                logger.warning("RATE_LIMIT_PER_MINUTE is not an integer, using 30")
                max_requests = 30

        return self.limit(max_requests=max_requests, window=window)


# Global rate limiter instance
rate_limiter = RateLimiter()
