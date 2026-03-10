"""
Unit tests for file validation functionality.

Tests cover:
- Extension validation against whitelist
- MIME type validation
- File size validation
- Edge cases (no extension, case sensitivity, etc.)
"""

import os
import sys
import unittest
from unittest.mock import Mock, patch

# Configure Django settings before importing Django modules
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'connector.settings')

import django
django.setup()

from etl_engine.file_validator import (
    get_file_extension,
    validate_file_type,
    validate_file_or_raise,
    FileValidationError,
    ALLOWED_EXTENSIONS,
    get_max_file_size,
    format_file_size
)


class TestGetFileExtension(unittest.TestCase):
    """Test file extension extraction."""
    
    def test_csv_extension(self):
        self.assertEqual(get_file_extension('data.csv'), '.csv')
    
    def test_excel_extensions(self):
        self.assertEqual(get_file_extension('data.xls'), '.xls')
        self.assertEqual(get_file_extension('data.xlsx'), '.xlsx')
    
    def test_parquet_extension(self):
        self.assertEqual(get_file_extension('data.parquet'), '.parquet')
    
    def test_case_insensitive(self):
        self.assertEqual(get_file_extension('DATA.CSV'), '.csv')
        self.assertEqual(get_file_extension('Data.XLS'), '.xls')
        self.assertEqual(get_file_extension('data.XLSX'), '.xlsx')
    
    def test_multiple_dots(self):
        self.assertEqual(get_file_extension('my.data.file.csv'), '.csv')
    
    def test_no_extension(self):
        self.assertEqual(get_file_extension('noextension'), '')
    
    def test_empty_filename(self):
        self.assertEqual(get_file_extension(''), '')
    
    def test_none_filename(self):
        self.assertEqual(get_file_extension(None), '')


class TestFormatFileSize(unittest.TestCase):
    """Test file size formatting."""
    
    def test_bytes(self):
        self.assertEqual(format_file_size(500), '500 bytes')
    
    def test_kilobytes(self):
        self.assertEqual(format_file_size(1024), '1.00 KB')
        self.assertEqual(format_file_size(2048), '2.00 KB')
        self.assertEqual(format_file_size(1536), '1.50 KB')
    
    def test_megabytes(self):
        self.assertEqual(format_file_size(1048576), '1.00 MB')
        self.assertEqual(format_file_size(5242880), '5.00 MB')
        self.assertEqual(format_file_size(1572864), '1.50 MB')
    
    def test_gigabytes(self):
        self.assertEqual(format_file_size(1073741824), '1.00 GB')
        self.assertEqual(format_file_size(2147483648), '2.00 GB')
        self.assertEqual(format_file_size(1610612736), '1.50 GB')


class TestFileSizeValidation(unittest.TestCase):
    """Test file size validation logic."""
    
    def create_mock_file(self, filename, size, content_type=None):
        """Helper to create a mock uploaded file with size."""
        mock_file = Mock()
        mock_file.name = filename
        mock_file.size = size
        if content_type:
            mock_file.content_type = content_type
        return mock_file
    
    @patch('etl_engine.file_validator.get_max_file_size')
    def test_file_within_size_limit(self, mock_get_max):
        """Test that files within size limit are accepted."""
        mock_get_max.return_value = 1073741824  # 1GB
        mock_file = self.create_mock_file('data.csv', 500000000, 'text/csv')  # 500MB
        is_valid, error = validate_file_type(mock_file)
        self.assertTrue(is_valid)
        self.assertEqual(error, '')
    
    @patch('etl_engine.file_validator.get_max_file_size')
    def test_file_exactly_at_size_limit(self, mock_get_max):
        """Test that files exactly at size limit are accepted."""
        mock_get_max.return_value = 1073741824  # 1GB
        mock_file = self.create_mock_file('data.csv', 1073741824, 'text/csv')  # Exactly 1GB
        is_valid, error = validate_file_type(mock_file)
        self.assertTrue(is_valid)
        self.assertEqual(error, '')
    
    @patch('etl_engine.file_validator.get_max_file_size')
    def test_file_exceeds_size_limit(self, mock_get_max):
        """Test that files exceeding size limit are rejected."""
        mock_get_max.return_value = 1073741824  # 1GB
        mock_file = self.create_mock_file('data.csv', 1073741825, 'text/csv')  # 1GB + 1 byte
        is_valid, error = validate_file_type(mock_file)
        self.assertFalse(is_valid)
        self.assertIn('exceeds maximum allowed size', error)
        self.assertIn('1.00 GB', error)
    
    @patch('etl_engine.file_validator.get_max_file_size')
    def test_large_file_error_message(self, mock_get_max):
        """Test that error message shows both actual and max size."""
        mock_get_max.return_value = 1073741824  # 1GB
        mock_file = self.create_mock_file('huge.csv', 2147483648, 'text/csv')  # 2GB
        is_valid, error = validate_file_type(mock_file)
        self.assertFalse(is_valid)
        self.assertIn('2.00 GB', error)  # Actual size
        self.assertIn('1.00 GB', error)  # Max size
    
    @patch('etl_engine.file_validator.get_max_file_size')
    def test_small_file_accepted(self, mock_get_max):
        """Test that small files are accepted."""
        mock_get_max.return_value = 1073741824  # 1GB
        mock_file = self.create_mock_file('small.csv', 1024, 'text/csv')  # 1KB
        is_valid, error = validate_file_type(mock_file)
        self.assertTrue(is_valid)
    
    @patch('etl_engine.file_validator.get_max_file_size')
    def test_zero_size_file(self, mock_get_max):
        """Test that zero-size files are accepted (size validation only)."""
        mock_get_max.return_value = 1073741824  # 1GB
        mock_file = self.create_mock_file('empty.csv', 0, 'text/csv')
        is_valid, error = validate_file_type(mock_file)
        self.assertTrue(is_valid)
    
    @patch('etl_engine.file_validator.get_max_file_size')
    def test_size_check_before_type_check(self, mock_get_max):
        """Test that size is checked before file type."""
        mock_get_max.return_value = 1073741824  # 1GB
        # Large file with invalid extension
        mock_file = self.create_mock_file('huge.txt', 2147483648, 'text/plain')  # 2GB
        is_valid, error = validate_file_type(mock_file)
        self.assertFalse(is_valid)
        # Should fail on size, not type
        self.assertIn('exceeds maximum allowed size', error)
    
    @patch('etl_engine.file_validator.get_max_file_size')
    def test_custom_size_limit(self, mock_get_max):
        """Test with custom size limit."""
        mock_get_max.return_value = 10485760  # 10MB
        mock_file = self.create_mock_file('data.csv', 20971520, 'text/csv')  # 20MB
        is_valid, error = validate_file_type(mock_file)
        self.assertFalse(is_valid)
        self.assertIn('20.00 MB', error)
        self.assertIn('10.00 MB', error)


class TestGetFileExtension(unittest.TestCase):
    """Test file extension extraction."""
    
    def test_csv_extension(self):
        self.assertEqual(get_file_extension('data.csv'), '.csv')
    
    def test_excel_extensions(self):
        self.assertEqual(get_file_extension('data.xls'), '.xls')
        self.assertEqual(get_file_extension('data.xlsx'), '.xlsx')
    
    def test_parquet_extension(self):
        self.assertEqual(get_file_extension('data.parquet'), '.parquet')
    
    def test_case_insensitive(self):
        self.assertEqual(get_file_extension('DATA.CSV'), '.csv')
        self.assertEqual(get_file_extension('Data.XLS'), '.xls')
        self.assertEqual(get_file_extension('data.XLSX'), '.xlsx')
    
    def test_multiple_dots(self):
        self.assertEqual(get_file_extension('my.data.file.csv'), '.csv')
    
    def test_no_extension(self):
        self.assertEqual(get_file_extension('noextension'), '')
    
    def test_empty_filename(self):
        self.assertEqual(get_file_extension(''), '')
    
    def test_none_filename(self):
        self.assertEqual(get_file_extension(None), '')


class TestValidateFileType(unittest.TestCase):
    """Test file type validation logic."""
    
    def create_mock_file(self, filename, content_type=None, size=1000):
        """Helper to create a mock uploaded file."""
        mock_file = Mock()
        mock_file.name = filename
        mock_file.size = size  # Default 1KB
        if content_type:
            mock_file.content_type = content_type
        return mock_file
    
    def test_valid_csv_file(self):
        mock_file = self.create_mock_file('data.csv', 'text/csv')
        is_valid, error = validate_file_type(mock_file)
        self.assertTrue(is_valid)
        self.assertEqual(error, '')
    
    def test_valid_csv_alternative_mime(self):
        # CSV files can have text/plain MIME type
        mock_file = self.create_mock_file('data.csv', 'text/plain')
        is_valid, error = validate_file_type(mock_file)
        self.assertTrue(is_valid)
        self.assertEqual(error, '')
    
    def test_valid_xls_file(self):
        mock_file = self.create_mock_file('data.xls', 'application/vnd.ms-excel')
        is_valid, error = validate_file_type(mock_file)
        self.assertTrue(is_valid)
        self.assertEqual(error, '')
    
    def test_valid_xlsx_file(self):
        mock_file = self.create_mock_file(
            'data.xlsx',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        is_valid, error = validate_file_type(mock_file)
        self.assertTrue(is_valid)
        self.assertEqual(error, '')
    
    def test_valid_parquet_file(self):
        mock_file = self.create_mock_file('data.parquet', 'application/octet-stream')
        is_valid, error = validate_file_type(mock_file)
        self.assertTrue(is_valid)
        self.assertEqual(error, '')
    
    def test_invalid_extension_txt(self):
        mock_file = self.create_mock_file('data.txt', 'text/plain')
        is_valid, error = validate_file_type(mock_file)
        self.assertFalse(is_valid)
        self.assertIn('.txt', error)
        self.assertIn('not allowed', error)
    
    def test_invalid_extension_json(self):
        mock_file = self.create_mock_file('data.json', 'application/json')
        is_valid, error = validate_file_type(mock_file)
        self.assertFalse(is_valid)
        self.assertIn('.json', error)
    
    def test_invalid_extension_pdf(self):
        mock_file = self.create_mock_file('document.pdf', 'application/pdf')
        is_valid, error = validate_file_type(mock_file)
        self.assertFalse(is_valid)
        self.assertIn('.pdf', error)
    
    def test_invalid_extension_exe(self):
        # Security test: executable files should be rejected
        mock_file = self.create_mock_file('malware.exe', 'application/x-msdownload')
        is_valid, error = validate_file_type(mock_file)
        self.assertFalse(is_valid)
        self.assertIn('.exe', error)
    
    def test_no_extension(self):
        mock_file = self.create_mock_file('noextension')
        is_valid, error = validate_file_type(mock_file)
        self.assertFalse(is_valid)
        self.assertIn('no extension', error)
    
    def test_mime_type_mismatch(self):
        # CSV extension but PDF MIME type
        mock_file = self.create_mock_file('fake.csv', 'application/pdf')
        is_valid, error = validate_file_type(mock_file)
        self.assertFalse(is_valid)
        self.assertIn('MIME type mismatch', error)
        self.assertIn('.csv', error)
        self.assertIn('application/pdf', error)
    
    def test_no_mime_type_provided(self):
        # Should still validate based on extension alone
        mock_file = Mock()
        mock_file.name = 'data.csv'
        mock_file.size = 1000  # Add size attribute
        # Don't set content_type attribute at all
        if hasattr(mock_file, 'content_type'):
            delattr(mock_file, 'content_type')
        
        is_valid, error = validate_file_type(mock_file)
        self.assertTrue(is_valid)
    
    def test_case_insensitive_extension(self):
        mock_file = self.create_mock_file('DATA.CSV', 'text/csv')
        is_valid, error = validate_file_type(mock_file)
        self.assertTrue(is_valid)
    
    def test_error_message_shows_allowed_types(self):
        mock_file = self.create_mock_file('data.txt')
        is_valid, error = validate_file_type(mock_file)
        self.assertFalse(is_valid)
        # Check that error message lists allowed types
        for ext in ALLOWED_EXTENSIONS:
            self.assertIn(ext, error)


class TestValidateFileOrRaise(unittest.TestCase):
    """Test the exception-raising validation function."""
    
    def create_mock_file(self, filename, content_type=None, size=1000):
        """Helper to create a mock uploaded file."""
        mock_file = Mock()
        mock_file.name = filename
        mock_file.size = size  # Default 1KB
        if content_type:
            mock_file.content_type = content_type
        return mock_file
    
    def test_valid_file_no_exception(self):
        mock_file = self.create_mock_file('data.csv', 'text/csv')
        # Should not raise
        try:
            validate_file_or_raise(mock_file)
        except FileValidationError:
            self.fail("validate_file_or_raise raised FileValidationError unexpectedly")
    
    def test_invalid_file_raises_exception(self):
        mock_file = self.create_mock_file('data.txt', 'text/plain')
        with self.assertRaises(FileValidationError) as context:
            validate_file_or_raise(mock_file)
        self.assertIn('.txt', str(context.exception))
    
    def test_exception_message_contains_details(self):
        mock_file = self.create_mock_file('malicious.exe')
        with self.assertRaises(FileValidationError) as context:
            validate_file_or_raise(mock_file)
        error_message = str(context.exception)
        self.assertIn('.exe', error_message)
        self.assertIn('not allowed', error_message)


class TestSecurityScenarios(unittest.TestCase):
    """Test security-related validation scenarios."""
    
    def create_mock_file(self, filename, content_type=None, size=1000):
        """Helper to create a mock uploaded file."""
        mock_file = Mock()
        mock_file.name = filename
        mock_file.size = size  # Default 1KB
        if content_type:
            mock_file.content_type = content_type
        return mock_file
    
    def test_double_extension_attack(self):
        # Attacker tries to bypass validation with double extension
        mock_file = self.create_mock_file('malware.exe.csv', 'text/csv')
        is_valid, error = validate_file_type(mock_file)
        # Should be valid because we only check the final extension
        self.assertTrue(is_valid)
    
    def test_script_file_rejected(self):
        mock_file = self.create_mock_file('script.sh', 'text/x-shellscript')
        is_valid, error = validate_file_type(mock_file)
        self.assertFalse(is_valid)
    
    def test_python_file_rejected(self):
        mock_file = self.create_mock_file('script.py', 'text/x-python')
        is_valid, error = validate_file_type(mock_file)
        self.assertFalse(is_valid)
    
    def test_zip_file_rejected(self):
        # Zip bombs are a security concern
        mock_file = self.create_mock_file('archive.zip', 'application/zip')
        is_valid, error = validate_file_type(mock_file)
        self.assertFalse(is_valid)


if __name__ == '__main__':
    unittest.main()


class TestVirusScanningIntegration(unittest.TestCase):
    """Test virus scanning integration in file validation."""
    
    def _create_mock_file(self, name, size=1000, content_type='text/csv'):
        """Helper to create mock uploaded file."""
        mock_file = Mock()
        mock_file.name = name
        mock_file.size = size
        mock_file.content_type = content_type
        mock_file.chunks.return_value = [b'test,data\n1,2\n']
        mock_file.seek = Mock()
        return mock_file
    
    @patch('etl_engine.file_validator.is_virus_scan_enabled')
    @patch('etl_engine.file_validator.scan_file')
    def test_clean_file_passes_virus_scan(self, mock_scan, mock_enabled):
        """Test that clean files pass virus scanning."""
        mock_enabled.return_value = True
        mock_scan.return_value = (True, None)  # Clean file
        
        mock_file = self._create_mock_file('data.csv')
        is_valid, error = validate_file_type(mock_file)
        
        self.assertTrue(is_valid)
        self.assertEqual(error, "")
    
    @patch('etl_engine.file_validator.is_virus_scan_enabled')
    @patch('etl_engine.file_validator.scan_file')
    def test_infected_file_rejected(self, mock_scan, mock_enabled):
        """Test that infected files are rejected."""
        mock_enabled.return_value = True
        mock_scan.return_value = (False, "Eicar-Test-Signature")  # Infected
        
        mock_file = self._create_mock_file('infected.csv')
        is_valid, error = validate_file_type(mock_file)
        
        self.assertFalse(is_valid)
        self.assertIn("virus detected", error.lower())
        self.assertIn("Eicar-Test-Signature", error)
    
    @patch('etl_engine.file_validator.is_virus_scan_enabled')
    def test_virus_scan_disabled(self, mock_enabled):
        """Test that files pass when virus scanning is disabled."""
        mock_enabled.return_value = False
        
        mock_file = self._create_mock_file('data.csv')
        is_valid, error = validate_file_type(mock_file)
        
        self.assertTrue(is_valid)
        self.assertEqual(error, "")
    
    @patch('etl_engine.file_validator.is_virus_scan_enabled')
    @patch('etl_engine.file_validator.scan_file')
    def test_virus_scan_can_be_skipped(self, mock_scan, mock_enabled):
        """Test that virus scanning can be skipped via parameter."""
        mock_enabled.return_value = True
        mock_scan.return_value = (False, "Test-Virus")
        
        mock_file = self._create_mock_file('data.csv')
        is_valid, error = validate_file_type(mock_file, skip_virus_scan=True)
        
        # Should pass because we skipped virus scan
        self.assertTrue(is_valid)
        self.assertEqual(error, "")
        # Verify scan_file was not called
        mock_scan.assert_not_called()
    
    @patch('etl_engine.file_validator.is_virus_scan_enabled')
    @patch('etl_engine.file_validator.scan_file')
    def test_file_pointer_reset_after_scan(self, mock_scan, mock_enabled):
        """Test that file pointer is reset after scanning."""
        mock_enabled.return_value = True
        mock_scan.return_value = (True, None)
        
        mock_file = self._create_mock_file('data.csv')
        validate_file_type(mock_file)
        
        # Verify seek(0) was called to reset file pointer
        mock_file.seek.assert_called_with(0)
    
    @patch('etl_engine.file_validator.is_virus_scan_enabled')
    @patch('etl_engine.file_validator.scan_file')
    @patch('etl_engine.file_validator.VirusScanError', Exception)
    def test_scan_error_logged_but_not_blocking(self, mock_scan, mock_enabled):
        """Test that scan errors are logged but don't block upload."""
        from etl_engine.file_validator import VirusScanError
        
        mock_enabled.return_value = True
        mock_scan.side_effect = VirusScanError("Scanner unavailable")
        
        mock_file = self._create_mock_file('data.csv')
        
        # Should still pass (fail-open for availability)
        is_valid, error = validate_file_type(mock_file)
        self.assertTrue(is_valid)


if __name__ == '__main__':
    unittest.main()
