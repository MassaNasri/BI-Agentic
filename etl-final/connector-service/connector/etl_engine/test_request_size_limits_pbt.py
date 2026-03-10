"""
Property-Based Tests for Request Size Limits

Tests universal properties that should hold for all request size validations:
- Requests below limit are always accepted
- Requests above limit are always rejected
- Boundary conditions are handled correctly
- Error messages are consistent and informative
"""

import unittest
from unittest.mock import Mock
from django.test import TestCase, RequestFactory, override_settings
from django.http import JsonResponse
from hypothesis import given, strategies as st, settings, assume
from .middleware import RequestValidationMiddleware


class RequestSizeLimitPropertyTest(TestCase):
    """Property-based tests for request size limit validation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.factory = RequestFactory()
        self.get_response = Mock(return_value=JsonResponse({'success': True}))
    
    @given(
        content_length=st.integers(min_value=0, max_value=1023),
        max_size=st.just(1024)
    )
    @settings(max_examples=50, deadline=None)
    @override_settings(MAX_REQUEST_SIZE=1024)
    def test_property_requests_below_limit_always_accepted(self, content_length, max_size):
        """
        Property: Any request with size < MAX_REQUEST_SIZE should be accepted.
        
        **Validates: Requirements NFR-4 (Security)**
        
        This property ensures that legitimate requests are never incorrectly rejected.
        """
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Create request with content length below limit
        request = self.factory.post('/api/test/', data={'key': 'value'})
        request.META['CONTENT_LENGTH'] = str(content_length)
        
        response = middleware(request)
        
        # Should be accepted (status 200)
        self.assertEqual(
            response.status_code, 200,
            f"Request with size {content_length} bytes should be accepted (limit: {max_size} bytes)"
        )
        
        # Should call get_response
        self.get_response.assert_called()
        self.get_response.reset_mock()
    
    @given(
        content_length=st.integers(min_value=1025, max_value=100000),
        max_size=st.just(1024)
    )
    @settings(max_examples=50, deadline=None)
    @override_settings(MAX_REQUEST_SIZE=1024)
    def test_property_requests_above_limit_always_rejected(self, content_length, max_size):
        """
        Property: Any request with size > MAX_REQUEST_SIZE should be rejected with 413.
        
        **Validates: Requirements NFR-4 (Security)**
        
        This property ensures that oversized requests are always blocked to prevent
        memory exhaustion and DoS attacks.
        """
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Create request with content length above limit
        request = self.factory.post('/api/test/', data={'key': 'value'})
        request.META['CONTENT_LENGTH'] = str(content_length)
        
        response = middleware(request)
        
        # Should be rejected (status 413)
        self.assertEqual(
            response.status_code, 413,
            f"Request with size {content_length} bytes should be rejected (limit: {max_size} bytes)"
        )
        
        # Should NOT call get_response
        self.get_response.assert_not_called()
        self.get_response.reset_mock()
    
    @given(max_size=st.integers(min_value=1024, max_value=10485760))
    @settings(max_examples=30, deadline=None)
    def test_property_boundary_at_exact_limit(self, max_size):
        """
        Property: Request at exactly MAX_REQUEST_SIZE should be accepted.
        
        **Validates: Requirements NFR-4 (Security)**
        
        This property verifies correct boundary handling - requests at the exact
        limit should be allowed (not rejected).
        """
        with override_settings(MAX_REQUEST_SIZE=max_size):
            middleware = RequestValidationMiddleware(self.get_response)
            
            # Create request with content length exactly at limit
            request = self.factory.post('/api/test/', data={'key': 'value'})
            request.META['CONTENT_LENGTH'] = str(max_size)
            
            response = middleware(request)
            
            # Should be accepted (boundary inclusive)
            self.assertEqual(
                response.status_code, 200,
                f"Request at exact limit {max_size} bytes should be accepted"
            )
            
            self.get_response.assert_called()
            self.get_response.reset_mock()
    
    @given(max_size=st.integers(min_value=1024, max_value=10485760))
    @settings(max_examples=30, deadline=None)
    def test_property_boundary_one_byte_over_limit(self, max_size):
        """
        Property: Request at MAX_REQUEST_SIZE + 1 should be rejected.
        
        **Validates: Requirements NFR-4 (Security)**
        
        This property verifies correct boundary handling - requests one byte over
        the limit should be rejected.
        """
        with override_settings(MAX_REQUEST_SIZE=max_size):
            middleware = RequestValidationMiddleware(self.get_response)
            
            # Create request with content length one byte over limit
            request = self.factory.post('/api/test/', data={'key': 'value'})
            request.META['CONTENT_LENGTH'] = str(max_size + 1)
            
            response = middleware(request)
            
            # Should be rejected
            self.assertEqual(
                response.status_code, 413,
                f"Request at {max_size + 1} bytes should be rejected (limit: {max_size} bytes)"
            )
            
            self.get_response.assert_not_called()
            self.get_response.reset_mock()
    
    @given(
        content_length=st.integers(min_value=1025, max_value=100000),
        max_size=st.just(1024)
    )
    @settings(max_examples=30, deadline=None)
    @override_settings(MAX_REQUEST_SIZE=1024)
    def test_property_rejected_requests_have_correlation_id(self, content_length, max_size):
        """
        Property: All rejected requests must have a correlation ID for tracking.
        
        **Validates: Requirements NFR-4 (Security), FR-10 (Observability)**
        
        This property ensures that all rejected requests can be traced and debugged
        using correlation IDs.
        """
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Create request exceeding limit
        request = self.factory.post('/api/test/', data={'key': 'value'})
        request.META['CONTENT_LENGTH'] = str(content_length)
        
        response = middleware(request)
        
        # Should have correlation ID in response body
        response_data = response.json()
        self.assertIn('correlation_id', response_data)
        self.assertIsNotNone(response_data['correlation_id'])
        self.assertNotEqual(response_data['correlation_id'], '')
        
        # Should have correlation ID in response headers
        self.assertIn('X-Correlation-ID', response)
        self.assertIsNotNone(response['X-Correlation-ID'])
    
    @given(
        content_length=st.integers(min_value=1025, max_value=100000),
        max_size=st.just(1024)
    )
    @settings(max_examples=30, deadline=None)
    @override_settings(MAX_REQUEST_SIZE=1024)
    def test_property_error_messages_are_informative(self, content_length, max_size):
        """
        Property: Error messages must include actual size and limit in human-readable format.
        
        **Validates: Requirements NFR-4 (Security)**
        
        This property ensures that error messages are helpful for debugging and
        provide clear information about why the request was rejected.
        """
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Create request exceeding limit
        request = self.factory.post('/api/test/', data={'key': 'value'})
        request.META['CONTENT_LENGTH'] = str(content_length)
        
        response = middleware(request)
        response_data = response.json()
        
        # Should have error message
        self.assertIn('message', response_data)
        message = response_data['message']
        
        # Message should mention "exceeds"
        self.assertIn('exceeds', message.lower())
        
        # Message should include size information (MB format)
        self.assertTrue(
            'MB' in message or 'mb' in message,
            f"Error message should include size in MB: {message}"
        )
    
    @given(
        content_length=st.integers(min_value=0, max_value=1023),
        max_size=st.just(1024)
    )
    @settings(max_examples=30, deadline=None)
    @override_settings(MAX_REQUEST_SIZE=1024)
    def test_property_accepted_requests_have_correlation_id(self, content_length, max_size):
        """
        Property: All accepted requests must have a correlation ID added to request object.
        
        **Validates: Requirements FR-10 (Observability)**
        
        This property ensures that all requests (accepted or rejected) can be traced
        through the system using correlation IDs.
        """
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Create request within limit
        request = self.factory.post('/api/test/', data={'key': 'value'})
        request.META['CONTENT_LENGTH'] = str(content_length)
        
        response = middleware(request)
        
        # Request should have correlation_id attribute
        self.assertTrue(hasattr(request, 'correlation_id'))
        self.assertIsNotNone(request.correlation_id)
        self.assertNotEqual(request.correlation_id, '')
        
        # Response should have correlation ID in headers
        self.assertIn('X-Correlation-ID', response)
    
    @given(max_size=st.integers(min_value=1024, max_value=10485760))
    @settings(max_examples=20, deadline=None)
    def test_property_requests_without_content_length_always_accepted(self, max_size):
        """
        Property: Requests without Content-Length header should always be accepted.
        
        **Validates: Requirements NFR-4 (Security)**
        
        This property ensures that GET requests and other requests without bodies
        are not incorrectly rejected.
        """
        with override_settings(MAX_REQUEST_SIZE=max_size):
            middleware = RequestValidationMiddleware(self.get_response)
            
            # Create request without Content-Length header
            request = self.factory.get('/api/test/')
            # Don't set CONTENT_LENGTH
            
            response = middleware(request)
            
            # Should be accepted
            self.assertEqual(response.status_code, 200)
            self.get_response.assert_called()
            self.get_response.reset_mock()
    
    @given(
        content_length=st.one_of(
            st.just('invalid'),
            st.just('abc'),
            st.just('-100'),
            st.just('1.5'),
            st.just('')
        ),
        max_size=st.just(1024)
    )
    @settings(max_examples=20, deadline=None)
    @override_settings(MAX_REQUEST_SIZE=1024)
    def test_property_invalid_content_length_handled_gracefully(self, content_length, max_size):
        """
        Property: Invalid Content-Length values should be handled gracefully (not crash).
        
        **Validates: Requirements NFR-4 (Security), NFR-3 (Reliability)**
        
        This property ensures that malformed headers don't cause crashes or
        unexpected behavior.
        """
        middleware = RequestValidationMiddleware(self.get_response)
        
        # Create request with invalid Content-Length
        request = self.factory.post('/api/test/', data={'key': 'value'})
        request.META['CONTENT_LENGTH'] = content_length
        
        # Should not raise exception
        try:
            response = middleware(request)
            # Should be accepted (invalid header ignored)
            self.assertEqual(response.status_code, 200)
        except Exception as e:
            self.fail(f"Invalid Content-Length should not cause exception: {e}")
        
        self.get_response.reset_mock()


if __name__ == '__main__':
    unittest.main()
