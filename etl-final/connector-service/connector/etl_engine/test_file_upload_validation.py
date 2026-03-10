"""
Integration tests for file upload validation in the connector service.

Tests the complete file upload flow including validation.
"""

from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from unittest.mock import patch, Mock
import json


class TestFileUploadValidation(TestCase):
    """Integration tests for file upload with validation."""
    
    def setUp(self):
        self.client = Client()
        self.upload_url = '/upload/'
    
    @patch('etl_engine.views.KafkaMessageProducer')
    @patch('etl_engine.views.SurrealClient')
    @patch('etl_engine.views.save_uploaded_file')
    def test_upload_valid_csv_file(self, mock_save, mock_surreal, mock_kafka):
        """Test uploading a valid CSV file."""
        mock_save.return_value = '/app/uploaded_files/test.csv'
        
        csv_content = b'name,age\nJohn,30\nJane,25'
        uploaded_file = SimpleUploadedFile(
            'data.csv',
            csv_content,
            content_type='text/csv'
        )
        
        response = self.client.post(self.upload_url, {'file': uploaded_file})
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('saved_path', data['data'])
    
    @patch('etl_engine.views.KafkaMessageProducer')
    @patch('etl_engine.views.SurrealClient')
    @patch('etl_engine.views.save_uploaded_file')
    def test_upload_valid_xlsx_file(self, mock_save, mock_surreal, mock_kafka):
        """Test uploading a valid Excel file."""
        mock_save.return_value = '/app/uploaded_files/test.xlsx'
        
        # Minimal Excel file content (not a real Excel file, but for testing)
        excel_content = b'PK\x03\x04'  # Excel files are ZIP archives
        uploaded_file = SimpleUploadedFile(
            'data.xlsx',
            excel_content,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
        response = self.client.post(self.upload_url, {'file': uploaded_file})
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
    
    @patch('etl_engine.views.KafkaMessageProducer')
    @patch('etl_engine.views.SurrealClient')
    @patch('etl_engine.views.save_uploaded_file')
    def test_upload_valid_parquet_file(self, mock_save, mock_surreal, mock_kafka):
        """Test uploading a valid Parquet file."""
        mock_save.return_value = '/app/uploaded_files/test.parquet'
        
        parquet_content = b'PAR1'  # Parquet magic bytes
        uploaded_file = SimpleUploadedFile(
            'data.parquet',
            parquet_content,
            content_type='application/octet-stream'
        )
        
        response = self.client.post(self.upload_url, {'file': uploaded_file})
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
    
    def test_upload_invalid_txt_file(self):
        """Test that TXT files are rejected."""
        txt_content = b'This is a text file'
        uploaded_file = SimpleUploadedFile(
            'data.txt',
            txt_content,
            content_type='text/plain'
        )
        
        response = self.client.post(self.upload_url, {'file': uploaded_file})
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('.txt', data['message'])
        self.assertIn('not allowed', data['message'])
    
    def test_upload_invalid_json_file(self):
        """Test that JSON files are rejected."""
        json_content = b'{"key": "value"}'
        uploaded_file = SimpleUploadedFile(
            'data.json',
            json_content,
            content_type='application/json'
        )
        
        response = self.client.post(self.upload_url, {'file': uploaded_file})
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('.json', data['message'])
    
    def test_upload_invalid_pdf_file(self):
        """Test that PDF files are rejected."""
        pdf_content = b'%PDF-1.4'
        uploaded_file = SimpleUploadedFile(
            'document.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        
        response = self.client.post(self.upload_url, {'file': uploaded_file})
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('.pdf', data['message'])
    
    def test_upload_executable_file_rejected(self):
        """Test that executable files are rejected (security)."""
        exe_content = b'MZ\x90\x00'  # DOS executable header
        uploaded_file = SimpleUploadedFile(
            'malware.exe',
            exe_content,
            content_type='application/x-msdownload'
        )
        
        response = self.client.post(self.upload_url, {'file': uploaded_file})
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('.exe', data['message'])
    
    def test_upload_file_no_extension(self):
        """Test that files without extension are rejected."""
        content = b'some content'
        uploaded_file = SimpleUploadedFile(
            'noextension',
            content,
            content_type='application/octet-stream'
        )
        
        response = self.client.post(self.upload_url, {'file': uploaded_file})
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('no extension', data['message'])
    
    def test_upload_mime_type_mismatch(self):
        """Test that MIME type mismatches are detected."""
        # File claims to be CSV but has PDF MIME type
        content = b'%PDF-1.4'
        uploaded_file = SimpleUploadedFile(
            'fake.csv',
            content,
            content_type='application/pdf'
        )
        
        response = self.client.post(self.upload_url, {'file': uploaded_file})
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('MIME type mismatch', data['message'])
    
    def test_upload_no_file_provided(self):
        """Test error when no file is provided."""
        response = self.client.post(self.upload_url, {})
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('No file provided', data['message'])
    
    @patch('etl_engine.views.KafkaMessageProducer')
    @patch('etl_engine.views.SurrealClient')
    @patch('etl_engine.views.save_uploaded_file')
    def test_upload_case_insensitive_extension(self, mock_save, mock_surreal, mock_kafka):
        """Test that file extensions are case-insensitive."""
        mock_save.return_value = '/app/uploaded_files/test.CSV'
        
        csv_content = b'name,age\nJohn,30'
        uploaded_file = SimpleUploadedFile(
            'DATA.CSV',
            csv_content,
            content_type='text/csv'
        )
        
        response = self.client.post(self.upload_url, {'file': uploaded_file})
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
    
    @patch('etl_engine.views.save_uploaded_file')
    def test_validation_happens_before_save(self, mock_save):
        """Test that validation occurs before file is saved."""
        # Upload invalid file
        txt_content = b'This is a text file'
        uploaded_file = SimpleUploadedFile(
            'data.txt',
            txt_content,
            content_type='text/plain'
        )
        
        response = self.client.post(self.upload_url, {'file': uploaded_file})
        
        # Validation should fail
        self.assertEqual(response.status_code, 400)
        
        # save_uploaded_file should NOT have been called
        mock_save.assert_not_called()
    
    def test_error_message_lists_allowed_types(self):
        """Test that error messages inform users of allowed types."""
        txt_content = b'This is a text file'
        uploaded_file = SimpleUploadedFile(
            'data.txt',
            txt_content,
            content_type='text/plain'
        )
        
        response = self.client.post(self.upload_url, {'file': uploaded_file})
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        message = data['message']
        
        # Should list all allowed types
        self.assertIn('.csv', message)
        self.assertIn('.xlsx', message)
        self.assertIn('.parquet', message)


class TestFileSizeValidation(TestCase):
    """Integration tests for file size validation."""
    
    def setUp(self):
        self.client = Client()
        self.upload_url = '/upload/'
    
    @patch('etl_engine.file_validator.get_max_file_size')
    @patch('etl_engine.views.KafkaMessageProducer')
    @patch('etl_engine.views.SurrealClient')
    @patch('etl_engine.views.save_uploaded_file')
    def test_upload_file_within_size_limit(self, mock_save, mock_surreal, mock_kafka, mock_get_max):
        """Test that files within size limit are accepted."""
        mock_get_max.return_value = 1073741824  # 1GB
        mock_save.return_value = '/app/uploaded_files/test.csv'
        
        # Create a small CSV file (1KB)
        csv_content = b'name,age\n' + b'John,30\n' * 50
        uploaded_file = SimpleUploadedFile(
            'data.csv',
            csv_content,
            content_type='text/csv'
        )
        
        response = self.client.post(self.upload_url, {'file': uploaded_file})
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
    
    @patch('etl_engine.file_validator.get_max_file_size')
    def test_upload_file_exceeds_size_limit(self, mock_get_max):
        """Test that files exceeding size limit are rejected."""
        mock_get_max.return_value = 1000  # 1KB limit for testing
        
        # Create a file larger than 1KB
        csv_content = b'name,age\n' + b'John,30\n' * 100
        uploaded_file = SimpleUploadedFile(
            'large.csv',
            csv_content,
            content_type='text/csv'
        )
        
        response = self.client.post(self.upload_url, {'file': uploaded_file})
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('exceeds maximum allowed size', data['message'])
    
    @patch('etl_engine.file_validator.get_max_file_size')
    def test_file_size_error_message_format(self, mock_get_max):
        """Test that file size error messages are human-readable."""
        mock_get_max.return_value = 1000  # 1KB limit
        
        # Create a 2KB file
        csv_content = b'x' * 2000
        uploaded_file = SimpleUploadedFile(
            'large.csv',
            csv_content,
            content_type='text/csv'
        )
        
        response = self.client.post(self.upload_url, {'file': uploaded_file})
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        message = data['message']
        
        # Should contain human-readable sizes
        self.assertIn('KB', message)  # Size units
        self.assertIn('exceeds', message)
    
    @patch('etl_engine.file_validator.get_max_file_size')
    @patch('etl_engine.views.save_uploaded_file')
    def test_size_validation_before_save(self, mock_save, mock_get_max):
        """Test that size validation occurs before file is saved."""
        mock_get_max.return_value = 1000  # 1KB limit
        
        # Create a large file
        csv_content = b'x' * 2000
        uploaded_file = SimpleUploadedFile(
            'large.csv',
            csv_content,
            content_type='text/csv'
        )
        
        response = self.client.post(self.upload_url, {'file': uploaded_file})
        
        # Should fail validation
        self.assertEqual(response.status_code, 400)
        
        # save_uploaded_file should NOT have been called
        mock_save.assert_not_called()
    
    @patch('etl_engine.file_validator.get_max_file_size')
    def test_size_check_before_type_check(self, mock_get_max):
        """Test that size is checked before file type."""
        mock_get_max.return_value = 1000  # 1KB limit
        
        # Create a large file with invalid extension
        content = b'x' * 2000
        uploaded_file = SimpleUploadedFile(
            'large.txt',
            content,
            content_type='text/plain'
        )
        
        response = self.client.post(self.upload_url, {'file': uploaded_file})
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        
        # Should fail on size, not type
        self.assertIn('exceeds maximum allowed size', data['message'])
