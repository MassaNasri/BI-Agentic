"""
Unit tests for virus scanner module.

Tests cover:
- ClamAV scanner functionality
- Mock scanner functionality
- Backend selection
- Error handling
- Configuration
"""

import unittest
import tempfile
import os
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings

from .virus_scanner import (
    ClamAVScanner,
    MockScanner,
    VirusScanError,
    VirusDetectedError,
    get_scanner_backend,
    is_virus_scan_enabled,
    scan_file,
    scan_file_or_raise,
)


class MockScannerTest(TestCase):
    """Test MockScanner backend."""
    
    def setUp(self):
        self.scanner = MockScanner()
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        # Clean up temp files
        for filename in os.listdir(self.temp_dir):
            os.unlink(os.path.join(self.temp_dir, filename))
        os.rmdir(self.temp_dir)
    
    def _create_temp_file(self, filename: str, content: str = "test") -> str:
        """Helper to create temporary test file."""
        filepath = os.path.join(self.temp_dir, filename)
        with open(filepath, 'w') as f:
            f.write(content)
        return filepath
    
    def test_clean_file(self):
        """Test that clean files pass mock scanner."""
        filepath = self._create_temp_file("clean_data.csv")
        is_clean, virus_name = self.scanner.scan_file(filepath)
        
        self.assertTrue(is_clean)
        self.assertIsNone(virus_name)
    
    def test_virus_in_filename(self):
        """Test that files with 'virus' in name are flagged."""
        filepath = self._create_temp_file("virus_test.csv")
        is_clean, virus_name = self.scanner.scan_file(filepath)
        
        self.assertFalse(is_clean)
        self.assertEqual(virus_name, "Test.Virus.Mock")
    
    def test_malware_in_filename(self):
        """Test that files with 'malware' in name are flagged."""
        filepath = self._create_temp_file("malware_sample.csv")
        is_clean, virus_name = self.scanner.scan_file(filepath)
        
        self.assertFalse(is_clean)
        self.assertEqual(virus_name, "Test.Virus.Mock")
    
    def test_case_insensitive(self):
        """Test that detection is case-insensitive."""
        filepath = self._create_temp_file("VIRUS_TEST.CSV")
        is_clean, virus_name = self.scanner.scan_file(filepath)
        
        self.assertFalse(is_clean)
        self.assertEqual(virus_name, "Test.Virus.Mock")


class ClamAVScannerTest(TestCase):
    """Test ClamAVScanner backend."""
    
    def setUp(self):
        self.scanner = ClamAVScanner(host='localhost', port=3310, timeout=30)
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        # Clean up temp files
        for filename in os.listdir(self.temp_dir):
            os.unlink(os.path.join(self.temp_dir, filename))
        os.rmdir(self.temp_dir)
    
    def _create_temp_file(self, filename: str, content: str = "test") -> str:
        """Helper to create temporary test file."""
        filepath = os.path.join(self.temp_dir, filename)
        with open(filepath, 'w') as f:
            f.write(content)
        return filepath
    
    @patch('socket.socket')
    def test_clean_file(self, mock_socket_class):
        """Test scanning clean file with ClamAV."""
        # Mock socket connection
        mock_socket = MagicMock()
        mock_socket_class.return_value = mock_socket
        mock_socket.recv.return_value = b'stream: OK\x00'
        
        filepath = self._create_temp_file("clean.csv")
        is_clean, virus_name = self.scanner.scan_file(filepath)
        
        self.assertTrue(is_clean)
        self.assertIsNone(virus_name)
        mock_socket.connect.assert_called_once_with(('localhost', 3310))
        mock_socket.close.assert_called_once()
    
    @patch('socket.socket')
    def test_infected_file(self, mock_socket_class):
        """Test scanning infected file with ClamAV."""
        # Mock socket connection
        mock_socket = MagicMock()
        mock_socket_class.return_value = mock_socket
        mock_socket.recv.return_value = b'stream: Eicar-Test-Signature FOUND\x00'
        
        filepath = self._create_temp_file("infected.csv")
        is_clean, virus_name = self.scanner.scan_file(filepath)
        
        self.assertFalse(is_clean)
        self.assertEqual(virus_name, "Eicar-Test-Signature")
    
    @patch('socket.socket')
    def test_connection_timeout(self, mock_socket_class):
        """Test handling of connection timeout."""
        # Mock socket timeout
        mock_socket = MagicMock()
        mock_socket_class.return_value = mock_socket
        mock_socket.connect.side_effect = TimeoutError()
        
        filepath = self._create_temp_file("test.csv")
        
        with self.assertRaises(VirusScanError) as context:
            self.scanner.scan_file(filepath)
        
        self.assertIn("timeout", str(context.exception).lower())
    
    @patch('socket.socket')
    def test_connection_error(self, mock_socket_class):
        """Test handling of connection error."""
        # Mock socket connection error
        mock_socket = MagicMock()
        mock_socket_class.return_value = mock_socket
        mock_socket.connect.side_effect = ConnectionRefusedError("Connection refused")
        
        filepath = self._create_temp_file("test.csv")
        
        with self.assertRaises(VirusScanError) as context:
            self.scanner.scan_file(filepath)
        
        self.assertIn("connection error", str(context.exception).lower())
    
    def test_file_not_found(self):
        """Test handling of non-existent file."""
        # Mock socket to avoid actual connection attempt
        with patch('socket.socket') as mock_socket_class:
            mock_socket = MagicMock()
            mock_socket_class.return_value = mock_socket
            
            with self.assertRaises(VirusScanError) as context:
                self.scanner.scan_file("/nonexistent/file.csv")
            
            # Check for either "not found" or "no such file"
            error_msg = str(context.exception).lower()
            self.assertTrue(
                "not found" in error_msg or "no such file" in error_msg,
                f"Expected file not found error, got: {error_msg}"
            )
    
    @patch('socket.socket')
    def test_unexpected_response(self, mock_socket_class):
        """Test handling of unexpected ClamAV response."""
        # Mock unexpected response
        mock_socket = MagicMock()
        mock_socket_class.return_value = mock_socket
        mock_socket.recv.return_value = b'stream: UNKNOWN\x00'
        
        filepath = self._create_temp_file("test.csv")
        
        with self.assertRaises(VirusScanError) as context:
            self.scanner.scan_file(filepath)
        
        self.assertIn("unexpected", str(context.exception).lower())


class BackendSelectionTest(TestCase):
    """Test scanner backend selection."""
    
    @override_settings(VIRUS_SCAN_BACKEND='mock')
    def test_mock_backend(self):
        """Test selecting mock backend."""
        backend = get_scanner_backend()
        self.assertIsInstance(backend, MockScanner)
    
    @override_settings(VIRUS_SCAN_BACKEND='clamav')
    def test_clamav_backend(self):
        """Test selecting ClamAV backend."""
        backend = get_scanner_backend()
        self.assertIsInstance(backend, ClamAVScanner)
    
    @override_settings(VIRUS_SCAN_BACKEND='invalid')
    def test_invalid_backend(self):
        """Test error on invalid backend."""
        with self.assertRaises(ValueError) as context:
            get_scanner_backend()
        
        self.assertIn("unknown", str(context.exception).lower())


class ConfigurationTest(TestCase):
    """Test configuration handling."""
    
    @override_settings(VIRUS_SCAN_ENABLED=True)
    def test_scanning_enabled(self):
        """Test that scanning can be enabled."""
        self.assertTrue(is_virus_scan_enabled())
    
    @override_settings(VIRUS_SCAN_ENABLED=False)
    def test_scanning_disabled(self):
        """Test that scanning can be disabled."""
        self.assertFalse(is_virus_scan_enabled())
    
    @override_settings(
        VIRUS_SCAN_BACKEND='clamav',
        CLAMAV_HOST='custom-host',
        CLAMAV_PORT=9999,
        CLAMAV_TIMEOUT=60
    )
    def test_clamav_configuration(self):
        """Test ClamAV configuration from settings."""
        backend = get_scanner_backend()
        
        self.assertIsInstance(backend, ClamAVScanner)
        self.assertEqual(backend.host, 'custom-host')
        self.assertEqual(backend.port, 9999)
        self.assertEqual(backend.timeout, 60)


class HighLevelAPITest(TestCase):
    """Test high-level API functions."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        # Clean up temp files
        for filename in os.listdir(self.temp_dir):
            os.unlink(os.path.join(self.temp_dir, filename))
        os.rmdir(self.temp_dir)
    
    def _create_temp_file(self, filename: str, content: str = "test") -> str:
        """Helper to create temporary test file."""
        filepath = os.path.join(self.temp_dir, filename)
        with open(filepath, 'w') as f:
            f.write(content)
        return filepath
    
    @override_settings(VIRUS_SCAN_ENABLED=True, VIRUS_SCAN_BACKEND='mock')
    def test_scan_file_clean(self):
        """Test scan_file with clean file."""
        filepath = self._create_temp_file("clean.csv")
        is_clean, virus_name = scan_file(filepath)
        
        self.assertTrue(is_clean)
        self.assertIsNone(virus_name)
    
    @override_settings(VIRUS_SCAN_ENABLED=True, VIRUS_SCAN_BACKEND='mock')
    def test_scan_file_infected(self):
        """Test scan_file with infected file."""
        filepath = self._create_temp_file("virus_test.csv")
        is_clean, virus_name = scan_file(filepath)
        
        self.assertFalse(is_clean)
        self.assertIsNotNone(virus_name)
    
    @override_settings(VIRUS_SCAN_ENABLED=False)
    def test_scan_file_disabled(self):
        """Test that scan_file returns clean when disabled."""
        filepath = self._create_temp_file("virus_test.csv")
        is_clean, virus_name = scan_file(filepath)
        
        # Should return clean even though filename contains 'virus'
        self.assertTrue(is_clean)
        self.assertIsNone(virus_name)
    
    @override_settings(VIRUS_SCAN_ENABLED=True, VIRUS_SCAN_BACKEND='mock')
    def test_scan_file_or_raise_clean(self):
        """Test scan_file_or_raise with clean file."""
        filepath = self._create_temp_file("clean.csv")
        
        # Should not raise
        try:
            scan_file_or_raise(filepath)
        except Exception as e:
            self.fail(f"scan_file_or_raise raised {e} unexpectedly")
    
    @override_settings(VIRUS_SCAN_ENABLED=True, VIRUS_SCAN_BACKEND='mock')
    def test_scan_file_or_raise_infected(self):
        """Test scan_file_or_raise with infected file."""
        filepath = self._create_temp_file("virus_test.csv")
        
        with self.assertRaises(VirusDetectedError) as context:
            scan_file_or_raise(filepath)
        
        self.assertIn("virus detected", str(context.exception).lower())


if __name__ == '__main__':
    unittest.main()
