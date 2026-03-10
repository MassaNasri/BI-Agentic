"""
Unit tests for request size limits in RequestValidationMiddleware.

Tests cover:
- Request size validation via Content-Length header
- Rejection of oversized requests
- Proper error messages and status codes
- Correlation ID tracking
- Configuration options
"""

import unittest
from unittest.mock import Mock, patch
from django.test import TestCase, RequestFactory, override_settings
from django.http import JsonResponse
from .middleware import RequestValidationMiddleware


class RequestSizeLimitTest(TestCase):
    """Test request size limit validation in middleware."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.factory = RequestFactory()
        self.get_response = Mock(return_value=JsonResponse({'success': True}))
    
    @override_settings(MAX_REQUEST_SIZE=1024)  # 1KB limit for testing
    def test_request_within_size_limit(self):
        """Test that requests within size limit are allowed."""
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Create request with Content-Length within limit
        request = self.factory.post('/api/test/', data={'key': 'value'})
        request.META['CONTENT_LENGTH'] = '512'  # 512 bytes
        
        response = middleware(request)
        
        # Should call get_response (request allowed)
        self.get_response.assert_called_once()
        self.assertEqual(response.status_code, 200)
    
    @override_settings(MAX_REQUEST_SIZE=1024)  # 1KB limit for testing
    def test_request_exceeds_size_limit(self):
        """Test that requests exceeding size limit are rejected."""
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Create request with Content-Length exceeding limit
        request = self.factory.post('/api/test/', data={'key': 'value'})
        request.META['CONTENT_LENGTH'] = '2048'  # 2KB (exceeds 1KB limit)
        
        response = middleware(request)
        
        # Should NOT call get_response (request rejected)
        self.get_response.assert_not_called()
        
        # Should return 413 Payload Too Large
        self.assertEqual(response.status_code, 413)
        
        # Should have error message
        response_data = response.json()
        self.assertFalse(response_data['success'])
        self.assertIn('exceeds maximum allowed size', response_data['message'])
    
    @override_settings(MAX_REQUEST_SIZE=10485760)  # 10MB limit
    def test_request_at_exact_size_limit(self):
        """Test request at exact size limit boundary."""
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Create request with Content-Length exactly at limit
        request = self.factory.post('/api/test/', data={'key': 'value'})
        request.META['CONTENT_LENGTH'] = '10485760'  # Exactly 10MB
        
        response = middleware(request)
        
        # Should call get_response (request allowed at boundary)
        self.get_response.assert_called_once()
        self.assertEqual(response.status_code, 200)
    
    @override_settings(MAX_REQUEST_SIZE=10485760)  # 10MB limit
    def test_request_one_byte_over_limit(self):
        """Test request one byte over size limit."""
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Create request with Content-Length one byte over limit
        request = self.factory.post('/api/test/', data={'key': 'value'})
        request.META['CONTENT_LENGTH'] = '10485761'  # 10MB + 1 byte
        
        response = middleware(request)
        
        # Should NOT call get_response (request rejected)
        self.get_response.assert_not_called()
        self.assertEqual(response.status_code, 413)
    
    def test_request_without_content_length_header(self):
        """Test request without Content-Length header is allowed."""
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Create request without Content-Length header
        request = self.factory.get('/api/test/')
        # Don't set CONTENT_LENGTH
        
        response = middleware(request)
        
        # Should call get_response (no size check without header)
        self.get_response.assert_called_once()
        self.assertEqual(response.status_code, 200)
    
    @override_settings(MAX_REQUEST_SIZE=1024)
    def test_request_with_invalid_content_length(self):
        """Test request with invalid Content-Length value."""
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Create request with invalid Content-Length
        request = self.factory.post('/api/test/', data={'key': 'value'})
        request.META['CONTENT_LENGTH'] = 'invalid'
        
        response = middleware(request)
        
        # Should call get_response (invalid header ignored)
        self.get_response.assert_called_once()
        self.assertEqual(response.status_code, 200)
    
    @override_settings(MAX_REQUEST_SIZE=1048576)  # 1MB
    def test_error_message_shows_sizes_in_mb(self):
        """Test that error message shows sizes in human-readable format."""
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Create request exceeding limit
        request = self.factory.post('/api/test/', data={'key': 'value'})
        request.META['CONTENT_LENGTH'] = '2097152'  # 2MB
        
        response = middleware(request)
        
        response_data = response.json()
        message = response_data['message']
        
        # Should show sizes in MB
        self.assertIn('2.00MB', message)
        self.assertIn('1.00MB', message)
    
    @override_settings(MAX_REQUEST_SIZE=1024)
    def test_correlation_id_added_to_response(self):
        """Test that correlation ID is added to rejected requests."""
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Create request exceeding limit
        request = self.factory.post('/api/test/', data={'key': 'value'})
        request.META['CONTENT_LENGTH'] = '2048'
        
        response = middleware(request)
        
        # Should have correlation ID in response
        response_data = response.json()
        self.assertIn('correlation_id', response_data)
        self.assertIsNotNone(response_data['correlation_id'])
        
        # Should also be in response headers
        self.assertIn('X-Correlation-ID', response)
    
    @override_settings(MAX_REQUEST_SIZE=1024)
    def test_correlation_id_in_request_object(self):
        """Test that correlation ID is added to request object."""
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Create valid request
        request = self.factory.post('/api/test/', data={'key': 'value'})
        request.META['CONTENT_LENGTH'] = '512'
        
        middleware(request)
        
        # Request should have correlation_id attribute
        self.assertTrue(hasattr(request, 'correlation_id'))
        self.assertIsNotNone(request.correlation_id)
    
    @override_settings(MAX_REQUEST_SIZE=5242880)  # 5MB
    def test_large_but_valid_request(self):
        """Test large request within configured limit."""
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Create request with 4MB content
        request = self.factory.post('/api/test/', data={'key': 'value'})
        request.META['CONTENT_LENGTH'] = '4194304'  # 4MB
        
        response = middleware(request)
        
        # Should be allowed
        self.get_response.assert_called_once()
        self.assertEqual(response.status_code, 200)
    
    def test_default_max_request_size(self):
        """Test default MAX_REQUEST_SIZE when not configured."""
        # Don't override settings, use default
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Default should be 10MB
        self.assertEqual(middleware.max_request_size, 10 * 1024 * 1024)
    
    @override_settings(MAX_REQUEST_SIZE=2097152)  # 2MB
    def test_get_request_with_no_body(self):
        """Test GET request with no body."""
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Create GET request (no body)
        request = self.factory.get('/api/test/')
        
        response = middleware(request)
        
        # Should be allowed
        self.get_response.assert_called_once()
        self.assertEqual(response.status_code, 200)
    
    @override_settings(MAX_REQUEST_SIZE=1024)
    def test_multiple_requests_with_different_sizes(self):
        """Test multiple requests with different sizes."""
        middleware = RequestValidationMiddleware(self.get_response)
        
        # First request: within limit
        request1 = self.factory.post('/api/test/', data={'key': 'value'})
        request1.META['CONTENT_LENGTH'] = '512'
        response1 = middleware(request1)
        self.assertEqual(response1.status_code, 200)
        
        # Reset mock
        self.get_response.reset_mock()
        
        # Second request: exceeds limit
        request2 = self.factory.post('/api/test/', data={'key': 'value'})
        request2.META['CONTENT_LENGTH'] = '2048'
        response2 = middleware(request2)
        self.assertEqual(response2.status_code, 413)
        
        # Reset mock
        self.get_response.reset_mock()
        
        # Third request: within limit again
        request3 = self.factory.post('/api/test/', data={'key': 'value'})
        request3.META['CONTENT_LENGTH'] = '256'
        response3 = middleware(request3)
        self.assertEqual(response3.status_code, 200)


class RequestSizeLimitIntegrationTest(TestCase):
    """Integration tests for request size limits with actual API endpoints."""
    
    @override_settings(MAX_REQUEST_SIZE=1024)  # 1KB limit for testing
    def test_connect_db_endpoint_with_oversized_payload(self):
        """Test ConnectDB endpoint rejects oversized payloads."""
        from rest_framework.test import APIClient
        
        client = APIClient()
        
        # Create large payload (> 1KB)
        large_data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "x" * 2000,  # Large password to exceed limit
            "database": "test_db"
        }
        
        response = client.post('/api/connect-db/', large_data, format='json')
        
        # Should be rejected by middleware before reaching view
        self.assertEqual(response.status_code, 413)
    
    @override_settings(MAX_REQUEST_SIZE=10485760)  # 10MB
    def test_connect_db_endpoint_with_normal_payload(self):
        """Test ConnectDB endpoint accepts normal-sized payloads."""
        from rest_framework.test import APIClient
        
        client = APIClient()
        
        # Create normal payload
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "password123",
            "database": "test_db"
        }
        
        response = client.post('/api/connect-db/', data, format='json')
        
        # Should pass middleware (may fail at connection test, but not at middleware)
        self.assertNotEqual(response.status_code, 413)


if __name__ == '__main__':
    unittest.main()
