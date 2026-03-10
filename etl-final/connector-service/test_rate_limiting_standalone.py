"""
Standalone unit tests for rate limiting middleware.
Tests the core rate limiting logic without requiring full Django setup.
"""

import time
import unittest
from unittest.mock import Mock, MagicMock
from collections import defaultdict
from threading import Lock
import sys
import os

# Add connector service to path
connector_path = os.path.join(os.path.dirname(__file__), 'connector')
if connector_path not in sys.path:
    sys.path.insert(0, connector_path)


class MockSettings:
    """Mock Django settings for testing."""
    RATE_LIMIT_ENABLED = True
    RATE_LIMIT_REQUESTS = 10
    RATE_LIMIT_WINDOW = 60
    RATE_LIMIT_PER_USER_REQUESTS = 20


class MockRequest:
    """Mock Django request object."""
    def __init__(self, ip='192.168.1.1', user=None):
        self.META = {'REMOTE_ADDR': ip}
        self.user = user
        self.correlation_id = 'test-correlation-id'


class MockUser:
    """Mock Django user object."""
    def __init__(self, username='testuser'):
        self.username = username
        self.is_authenticated = True


class RateLimitMiddlewareStandalone:
    """
    Standalone version of RateLimitMiddleware for testing.
    Contains the core rate limiting logic without Django dependencies.
    """
    
    def __init__(self, settings):
        self.rate_limit_enabled = settings.RATE_LIMIT_ENABLED
        self.rate_limit_requests = settings.RATE_LIMIT_REQUESTS
        self.rate_limit_window = settings.RATE_LIMIT_WINDOW
        self.rate_limit_per_user_requests = settings.RATE_LIMIT_PER_USER_REQUESTS
        
        self.request_counts = defaultdict(list)
        self.lock = Lock()
        
        self.stats = {
            'total_requests': 0,
            'rate_limited_requests': 0,
            'unique_ips': set(),
            'unique_users': set()
        }
        self.stats_lock = Lock()
    
    def _get_client_ip(self, request):
        """Extract client IP address from request."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', 'unknown')
        return ip
    
    def _get_user_identifier(self, request):
        """Extract user identifier from authenticated request."""
        if hasattr(request, 'user') and hasattr(request.user, 'is_authenticated') and request.user.is_authenticated:
            return request.user.username
        return None
    
    def _check_rate_limit(self, identifier, limit):
        """Check if identifier has exceeded rate limit using sliding window."""
        with self.lock:
            current_time = time.time()
            window_start = current_time - self.rate_limit_window
            
            if identifier in self.request_counts:
                # Remove old requests outside window
                self.request_counts[identifier] = [
                    ts for ts in self.request_counts[identifier]
                    if ts > window_start
                ]
                
                current_count = len(self.request_counts[identifier])
                remaining = max(0, limit - current_count)
                
                if current_count >= limit:
                    return True, 0
                
                return False, remaining
            
            return False, limit
    
    def _record_request(self, identifier):
        """Record a request for rate limiting."""
        with self.lock:
            current_time = time.time()
            self.request_counts[identifier].append(current_time)
    
    def check_request(self, request):
        """
        Check if request should be rate limited.
        Returns: (is_limited, limit_type, remaining)
        """
        if not self.rate_limit_enabled:
            return False, None, None
        
        with self.stats_lock:
            self.stats['total_requests'] += 1
        
        client_ip = self._get_client_ip(request)
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
            with self.stats_lock:
                self.stats['rate_limited_requests'] += 1
            
            limit_type = "user" if user_limited else "IP"
            return True, limit_type, 0
        
        # Record request for both IP and user
        self._record_request(f"ip:{client_ip}")
        if user_identifier:
            self._record_request(f"user:{user_identifier}")
        
        # Update statistics
        with self.stats_lock:
            self.stats['unique_ips'].add(client_ip)
            if user_identifier:
                self.stats['unique_users'].add(user_identifier)
        
        return False, None, user_remaining if user_identifier else ip_remaining
    
    def get_stats(self):
        """Get rate limiting statistics for monitoring."""
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


class TestRateLimiting(unittest.TestCase):
    """Test rate limiting functionality."""
    
    def test_rate_limit_disabled(self):
        """Test that rate limiting can be disabled."""
        settings = MockSettings()
        settings.RATE_LIMIT_ENABLED = False
        middleware = RateLimitMiddlewareStandalone(settings)
        
        # Make many requests - should all succeed
        for i in range(150):
            request = MockRequest()
            is_limited, _, _ = middleware.check_request(request)
            self.assertFalse(is_limited)
    
    def test_per_ip_rate_limiting(self):
        """Test that requests are rate limited per IP address."""
        settings = MockSettings()
        settings.RATE_LIMIT_REQUESTS = 10
        middleware = RateLimitMiddlewareStandalone(settings)
        
        # Make requests up to the limit
        for i in range(10):
            request = MockRequest(ip='192.168.1.1')
            is_limited, _, _ = middleware.check_request(request)
            self.assertFalse(is_limited)
        
        # Next request should be rate limited
        request = MockRequest(ip='192.168.1.1')
        is_limited, limit_type, _ = middleware.check_request(request)
        self.assertTrue(is_limited)
        self.assertEqual(limit_type, 'IP')
    
    def test_different_ips_independent_limits(self):
        """Test that different IPs have independent rate limits."""
        settings = MockSettings()
        settings.RATE_LIMIT_REQUESTS = 5
        middleware = RateLimitMiddlewareStandalone(settings)
        
        # IP 1: Make requests up to limit
        for i in range(5):
            request = MockRequest(ip='192.168.1.1')
            is_limited, _, _ = middleware.check_request(request)
            self.assertFalse(is_limited)
        
        # IP 1: Should be rate limited
        request = MockRequest(ip='192.168.1.1')
        is_limited, _, _ = middleware.check_request(request)
        self.assertTrue(is_limited)
        
        # IP 2: Should still work (independent limit)
        for i in range(5):
            request = MockRequest(ip='192.168.1.2')
            is_limited, _, _ = middleware.check_request(request)
            self.assertFalse(is_limited)
    
    def test_x_forwarded_for_header(self):
        """Test that X-Forwarded-For header is respected."""
        settings = MockSettings()
        settings.RATE_LIMIT_REQUESTS = 5
        middleware = RateLimitMiddlewareStandalone(settings)
        
        # Make requests with X-Forwarded-For header
        for i in range(5):
            request = MockRequest(ip='192.168.1.100')
            request.META['HTTP_X_FORWARDED_FOR'] = '10.0.0.1, 192.168.1.1'
            is_limited, _, _ = middleware.check_request(request)
            self.assertFalse(is_limited)
        
        # Next request should be rate limited (based on first IP in X-Forwarded-For)
        request = MockRequest(ip='192.168.1.100')
        request.META['HTTP_X_FORWARDED_FOR'] = '10.0.0.1, 192.168.1.1'
        is_limited, _, _ = middleware.check_request(request)
        self.assertTrue(is_limited)
    
    def test_per_user_rate_limiting(self):
        """Test that authenticated users have separate rate limits."""
        settings = MockSettings()
        settings.RATE_LIMIT_REQUESTS = 5
        settings.RATE_LIMIT_PER_USER_REQUESTS = 10
        middleware = RateLimitMiddlewareStandalone(settings)
        
        user = MockUser(username='testuser')
        
        # Make requests as authenticated user from different IPs
        # This tests that user limit is independent of IP limit
        for i in range(10):
            # Use different IPs to avoid hitting IP limit
            request = MockRequest(ip=f'192.168.1.{i}', user=user)
            is_limited, _, _ = middleware.check_request(request)
            self.assertFalse(is_limited, f"Request {i} should not be limited")
        
        # Next request should be rate limited (user limit exceeded)
        request = MockRequest(ip='192.168.1.100', user=user)
        is_limited, limit_type, _ = middleware.check_request(request)
        self.assertTrue(is_limited)
        self.assertEqual(limit_type, 'user')
    
    def test_sliding_window_algorithm(self):
        """Test that sliding window algorithm works correctly."""
        settings = MockSettings()
        settings.RATE_LIMIT_REQUESTS = 5
        settings.RATE_LIMIT_WINDOW = 2  # 2 second window for faster testing
        middleware = RateLimitMiddlewareStandalone(settings)
        
        # Make 5 requests (fill the limit)
        for i in range(5):
            request = MockRequest(ip='192.168.1.1')
            is_limited, _, _ = middleware.check_request(request)
            self.assertFalse(is_limited)
        
        # Next request should be rate limited
        request = MockRequest(ip='192.168.1.1')
        is_limited, _, _ = middleware.check_request(request)
        self.assertTrue(is_limited)
        
        # Wait for window to expire
        time.sleep(2.1)
        
        # Should be able to make requests again
        request = MockRequest(ip='192.168.1.1')
        is_limited, _, _ = middleware.check_request(request)
        self.assertFalse(is_limited)
    
    def test_statistics_tracking(self):
        """Test that statistics are tracked correctly."""
        settings = MockSettings()
        settings.RATE_LIMIT_REQUESTS = 5
        middleware = RateLimitMiddlewareStandalone(settings)
        
        # Make some successful requests
        for i in range(5):
            request = MockRequest(ip='192.168.1.1')
            middleware.check_request(request)
        
        # Make a rate limited request
        request = MockRequest(ip='192.168.1.1')
        middleware.check_request(request)
        
        # Check statistics
        stats = middleware.get_stats()
        self.assertEqual(stats['total_requests'], 6)
        self.assertEqual(stats['rate_limited_requests'], 1)
        self.assertEqual(stats['unique_ips'], 1)
    
    def test_concurrent_requests_thread_safety(self):
        """Test that middleware is thread-safe for concurrent requests."""
        import threading
        
        settings = MockSettings()
        settings.RATE_LIMIT_REQUESTS = 50
        middleware = RateLimitMiddlewareStandalone(settings)
        
        results = []
        
        def make_request():
            request = MockRequest(ip='192.168.1.1')
            is_limited, _, _ = middleware.check_request(request)
            results.append(is_limited)
        
        # Make 60 concurrent requests (should exceed limit of 50)
        threads = []
        for i in range(60):
            thread = threading.Thread(target=make_request)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Verify that some requests succeeded and some were rate limited
        success_count = results.count(False)
        rate_limited_count = results.count(True)
        
        self.assertLessEqual(success_count, 50)  # At most 50 should succeed
        self.assertGreater(rate_limited_count, 0)  # At least some should be rate limited
        self.assertEqual(len(results), 60)  # All requests completed


if __name__ == '__main__':
    # Run tests
    unittest.main(verbosity=2)
