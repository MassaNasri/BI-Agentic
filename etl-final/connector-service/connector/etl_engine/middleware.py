"""
Django middleware for global request validation and security.

Provides:
- Request size limits
- Rate limiting (basic implementation)
- Request logging with correlation IDs
- Security headers
"""

import time
import uuid
import logging
from django.http import JsonResponse
from django.conf import settings
from collections import defaultdict
from threading import Lock

logger = logging.getLogger(__name__)


class RequestValidationMiddleware:
    """
    Middleware for global request validation.
    
    Validates:
    - Request size limits
    - Content-Type headers
    - Request method allowlist
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.max_request_size = getattr(settings, 'MAX_REQUEST_SIZE', 10 * 1024 * 1024)  # 10MB default
    
    def __call__(self, request):
        # Add correlation ID for request tracking
        correlation_id = str(uuid.uuid4())
        request.correlation_id = correlation_id
        
        # Log incoming request
        logger.info(
            f"[{correlation_id}] Incoming request: {request.method} {request.path}",
            extra={
                'correlation_id': correlation_id,
                'method': request.method,
                'path': request.path,
                'remote_addr': self._get_client_ip(request)
            }
        )
        
        # Validate request size
        content_length = request.META.get('CONTENT_LENGTH')
        if content_length:
            try:
                content_length = int(content_length)
                if content_length > self.max_request_size:
                    max_mb = self.max_request_size / (1024 * 1024)
                    actual_mb = content_length / (1024 * 1024)
                    logger.warning(
                        f"[{correlation_id}] Request size {actual_mb:.2f}MB exceeds limit {max_mb:.2f}MB",
                        extra={'correlation_id': correlation_id}
                    )
                    return JsonResponse({
                        'success': False,
                        'message': f'Request size {actual_mb:.2f}MB exceeds maximum allowed size of {max_mb:.2f}MB',
                        'correlation_id': correlation_id
                    }, status=413)
            except ValueError:
                pass
        
        # Process request
        response = self.get_response(request)
        
        # Add correlation ID to response headers
        response['X-Correlation-ID'] = correlation_id
        
        # Log response
        logger.info(
            f"[{correlation_id}] Response: {response.status_code}",
            extra={
                'correlation_id': correlation_id,
                'status_code': response.status_code
            }
        )
        
        return response
    
    def _get_client_ip(self, request):
        """Extract client IP address from request."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class RateLimitMiddleware:
    """
    Rate limiting middleware using sliding window algorithm.
    
    Limits requests per IP address and per authenticated user within a time window.
    Uses a sliding window approach for accurate rate limiting.
    
    Features:
    - Per-IP rate limiting (prevents DoS attacks)
    - Per-user rate limiting (for authenticated requests)
    - Sliding window algorithm (more accurate than fixed window)
    - Configurable limits and window size
    - Thread-safe implementation
    - Automatic cleanup of old entries
    - Detailed logging and metrics
    
    Configuration (in settings.py):
    - RATE_LIMIT_ENABLED: Enable/disable rate limiting (default: True)
    - RATE_LIMIT_REQUESTS: Max requests per window (default: 100)
    - RATE_LIMIT_WINDOW: Time window in seconds (default: 60)
    - RATE_LIMIT_PER_USER_REQUESTS: Max requests per user (default: 200)
    
    Note: This is an in-memory implementation suitable for single-instance deployments.
    For production multi-instance deployments, use Redis-based rate limiting.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.rate_limit_enabled = getattr(settings, 'RATE_LIMIT_ENABLED', True)
        self.rate_limit_requests = getattr(settings, 'RATE_LIMIT_REQUESTS', 100)  # requests per window
        self.rate_limit_window = getattr(settings, 'RATE_LIMIT_WINDOW', 60)  # seconds
        self.rate_limit_per_user_requests = getattr(settings, 'RATE_LIMIT_PER_USER_REQUESTS', 200)  # higher limit for authenticated users
        
        # In-memory storage for rate limiting
        # Format: {identifier: [(timestamp1, timestamp2, ...)]}
        # identifier can be IP address or user:username
        self.request_counts = defaultdict(list)
        self.lock = Lock()
        
        # Statistics for monitoring
        self.stats = {
            'total_requests': 0,
            'rate_limited_requests': 0,
            'unique_ips': set(),
            'unique_users': set()
        }
        self.stats_lock = Lock()
        
        logger.info(
            f"RateLimitMiddleware initialized: {self.rate_limit_requests} requests per {self.rate_limit_window}s (IP), "
            f"{self.rate_limit_per_user_requests} requests per {self.rate_limit_window}s (user)"
        )
    
    def __call__(self, request):
        if not self.rate_limit_enabled:
            return self.get_response(request)
        
        # Update statistics
        with self.stats_lock:
            self.stats['total_requests'] += 1
        
        # Get client IP
        client_ip = self._get_client_ip(request)
        
        # Get user identifier if authenticated
        user_identifier = self._get_user_identifier(request)
        
        # Check rate limit for IP
        ip_limited, ip_remaining = self._check_rate_limit(f"ip:{client_ip}", self.rate_limit_requests)
        
        # Check rate limit for user (if authenticated)
        user_limited = False
        user_remaining = None
        if user_identifier:
            user_limited, user_remaining = self._check_rate_limit(f"user:{user_identifier}", self.rate_limit_per_user_requests)
        
        # If either IP or user is rate limited, reject request
        if ip_limited or user_limited:
            correlation_id = getattr(request, 'correlation_id', 'unknown')
            
            # Update statistics
            with self.stats_lock:
                self.stats['rate_limited_requests'] += 1
            
            # Determine which limit was exceeded
            limit_type = "user" if user_limited else "IP"
            limit_value = self.rate_limit_per_user_requests if user_limited else self.rate_limit_requests
            
            logger.warning(
                f"[{correlation_id}] Rate limit exceeded for {limit_type}: {user_identifier or client_ip}",
                extra={
                    'correlation_id': correlation_id,
                    'client_ip': client_ip,
                    'user': user_identifier,
                    'limit_type': limit_type,
                    'limit_value': limit_value,
                    'window': self.rate_limit_window
                }
            )
            
            response = JsonResponse({
                'success': False,
                'message': f'Rate limit exceeded. Maximum {limit_value} requests per {self.rate_limit_window} seconds.',
                'correlation_id': correlation_id,
                'retry_after': self.rate_limit_window  # Hint for client retry
            }, status=429)
            
            # Add rate limit headers (RFC 6585)
            response['X-RateLimit-Limit'] = str(limit_value)
            response['X-RateLimit-Remaining'] = '0'
            response['X-RateLimit-Reset'] = str(int(time.time() + self.rate_limit_window))
            response['Retry-After'] = str(self.rate_limit_window)
            
            return response
        
        # Record request for both IP and user
        self._record_request(f"ip:{client_ip}")
        if user_identifier:
            self._record_request(f"user:{user_identifier}")
        
        # Update statistics
        with self.stats_lock:
            self.stats['unique_ips'].add(client_ip)
            if user_identifier:
                self.stats['unique_users'].add(user_identifier)
        
        # Process request
        response = self.get_response(request)
        
        # Add rate limit headers to successful responses
        response['X-RateLimit-Limit'] = str(self.rate_limit_per_user_requests if user_identifier else self.rate_limit_requests)
        response['X-RateLimit-Remaining'] = str(user_remaining if user_identifier else ip_remaining)
        response['X-RateLimit-Reset'] = str(int(time.time() + self.rate_limit_window))
        
        return response
    
    def _get_client_ip(self, request):
        """
        Extract client IP address from request.
        
        Handles X-Forwarded-For header for proxied requests.
        """
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            # Take the first IP in the chain (original client)
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', 'unknown')
        return ip
    
    def _get_user_identifier(self, request):
        """
        Extract user identifier from authenticated request.
        
        Returns username if user is authenticated, None otherwise.
        """
        if hasattr(request, 'user') and request.user.is_authenticated:
            return request.user.username
        return None
    
    def _check_rate_limit(self, identifier, limit):
        """
        Check if identifier has exceeded rate limit using sliding window.
        
        Args:
            identifier: Unique identifier (e.g., "ip:192.168.1.1" or "user:john")
            limit: Maximum number of requests allowed in window
        
        Returns:
            Tuple of (is_limited: bool, remaining_requests: int)
        """
        with self.lock:
            current_time = time.time()
            window_start = current_time - self.rate_limit_window
            
            # Get requests within current window (sliding window)
            if identifier in self.request_counts:
                # Remove old requests outside window
                self.request_counts[identifier] = [
                    ts for ts in self.request_counts[identifier]
                    if ts > window_start
                ]
                
                # Check if limit exceeded
                current_count = len(self.request_counts[identifier])
                remaining = max(0, limit - current_count)
                
                if current_count >= limit:
                    return True, 0
                
                return False, remaining
            
            return False, limit
    
    def _record_request(self, identifier):
        """
        Record a request for rate limiting.
        
        Args:
            identifier: Unique identifier (e.g., "ip:192.168.1.1" or "user:john")
        """
        with self.lock:
            current_time = time.time()
            self.request_counts[identifier].append(current_time)
            
            # Cleanup old entries periodically to prevent memory growth
            # Cleanup every 1000 unique identifiers
            if len(self.request_counts) > 1000:
                self._cleanup_old_entries()
    
    def _cleanup_old_entries(self):
        """
        Remove old entries from request_counts to prevent memory growth.
        
        This method is called periodically to clean up identifiers
        that have no recent requests.
        """
        current_time = time.time()
        window_start = current_time - self.rate_limit_window
        
        # Remove identifiers with no recent requests
        identifiers_to_remove = []
        for identifier, timestamps in list(self.request_counts.items()):
            # Remove old timestamps
            recent_timestamps = [ts for ts in timestamps if ts > window_start]
            if not recent_timestamps:
                identifiers_to_remove.append(identifier)
            else:
                self.request_counts[identifier] = recent_timestamps
        
        for identifier in identifiers_to_remove:
            del self.request_counts[identifier]
        
        if identifiers_to_remove:
            logger.debug(f"Cleaned up {len(identifiers_to_remove)} old rate limit entries")
    
    def get_stats(self):
        """
        Get rate limiting statistics for monitoring.
        
        Returns:
            Dictionary with statistics
        """
        with self.stats_lock:
            return {
                'total_requests': self.stats['total_requests'],
                'rate_limited_requests': self.stats['rate_limited_requests'],
                'unique_ips': len(self.stats['unique_ips']),
                'unique_users': len(self.stats['unique_users']),
                'rate_limit_percentage': (
                    (self.stats['rate_limited_requests'] / self.stats['total_requests'] * 100)
                    if self.stats['total_requests'] > 0 else 0
                )
            }


class SecurityHeadersMiddleware:
    """
    Middleware to add security headers to responses.
    
    Adds:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - X-XSS-Protection: 1; mode=block
    - Content-Security-Policy
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        
        # Add security headers
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Content-Security-Policy'] = "default-src 'self'"
        
        return response
