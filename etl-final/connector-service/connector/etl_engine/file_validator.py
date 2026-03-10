"""
File validation utilities for the connector service.

Implements security-focused file validation including:
- File type whitelisting (CSV, Excel, Parquet)
- Extension validation
- MIME type validation
- File size limits (configurable, default 1GB)
- Virus scanning (ClamAV or mock)
"""

import mimetypes
import os
import tempfile
from typing import Tuple
from django.conf import settings
from .virus_scanner import scan_file, VirusScanError, is_virus_scan_enabled


# Whitelist of allowed file extensions
ALLOWED_EXTENSIONS = {'.csv', '.xls', '.xlsx', '.parquet'}

# Mapping of extensions to expected MIME types
MIME_TYPE_MAPPING = {
    '.csv': {'text/csv', 'text/plain', 'application/csv'},
    '.xls': {'application/vnd.ms-excel', 'application/octet-stream'},
    '.xlsx': {
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/octet-stream'
    },
    '.parquet': {'application/octet-stream', 'application/x-parquet'}
}


def get_max_file_size() -> int:
    """
    Get the maximum allowed file size from settings.
    
    Returns:
        Maximum file size in bytes (default: 1GB)
    """
    return getattr(settings, 'MAX_FILE_SIZE', 1073741824)  # 1GB default


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format.
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        Formatted string (e.g., "1.5 GB", "500 MB")
    """
    if size_bytes >= 1073741824:  # GB
        return f"{size_bytes / 1073741824:.2f} GB"
    elif size_bytes >= 1048576:  # MB
        return f"{size_bytes / 1048576:.2f} MB"
    elif size_bytes >= 1024:  # KB
        return f"{size_bytes / 1024:.2f} KB"
    else:
        return f"{size_bytes} bytes"


class FileValidationError(Exception):
    """Raised when file validation fails."""
    pass


def get_file_extension(filename: str) -> str:
    """
    Extract and normalize file extension from filename.
    
    Args:
        filename: The name of the file
        
    Returns:
        Lowercase file extension including the dot (e.g., '.csv')
    """
    if not filename or '.' not in filename:
        return ''
    
    return '.' + filename.rsplit('.', 1)[1].lower()


def validate_file_type(uploaded_file, skip_virus_scan: bool = False) -> Tuple[bool, str]:
    """
    Validate that the uploaded file is an allowed type and within size limits.
    
    Performs four-level validation:
    1. File size check against configured limit
    2. Extension check against whitelist
    3. MIME type verification (if available)
    4. Virus scanning (if enabled and not skipped)
    
    Args:
        uploaded_file: Django UploadedFile object
        skip_virus_scan: Skip virus scanning (for testing)
        
    Returns:
        Tuple of (is_valid, error_message)
        - (True, "") if validation passes
        - (False, error_message) if validation fails
    """
    filename = uploaded_file.name
    
    # Validate file size
    file_size = uploaded_file.size
    max_size = get_max_file_size()
    
    if file_size > max_size:
        return False, (
            f"File size {format_file_size(file_size)} exceeds maximum allowed size "
            f"of {format_file_size(max_size)}"
        )
    
    # Validate extension
    extension = get_file_extension(filename)
    
    if not extension:
        return False, "File has no extension"
    
    if extension not in ALLOWED_EXTENSIONS:
        allowed_list = ', '.join(sorted(ALLOWED_EXTENSIONS))
        return False, f"File type '{extension}' not allowed. Allowed types: {allowed_list}"
    
    # Validate MIME type if available
    content_type = getattr(uploaded_file, 'content_type', None)
    
    if content_type and content_type != '':
        expected_mime_types = MIME_TYPE_MAPPING.get(extension, set())
        
        if expected_mime_types and content_type not in expected_mime_types:
            return False, (
                f"MIME type mismatch: file extension is '{extension}' "
                f"but MIME type is '{content_type}'"
            )
    
    # Virus scanning (if enabled and not skipped)
    if not skip_virus_scan and is_virus_scan_enabled():
        temp_file_path = None
        try:
            # Write uploaded file to temporary location for scanning
            with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as temp_file:
                temp_file_path = temp_file.name
                
                # Write file contents
                for chunk in uploaded_file.chunks():
                    temp_file.write(chunk)
            
            # Scan the temporary file
            is_clean, virus_name = scan_file(temp_file_path)
            
            if not is_clean:
                return False, f"Virus detected: {virus_name}"
        
        except VirusScanError as e:
            # Log error but don't block upload if scanning fails
            # This prevents DoS if virus scanner is down
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Virus scan failed for {filename}: {e}")
            # Optionally: return False, f"Virus scan failed: {e}"
        
        finally:
            # Clean up temporary file
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    pass
            
            # Reset file pointer for subsequent reads
            if hasattr(uploaded_file, 'seek'):
                uploaded_file.seek(0)
    
    return True, ""


def validate_file_or_raise(uploaded_file) -> None:
    """
    Validate file type and raise FileValidationError if invalid.
    
    Args:
        uploaded_file: Django UploadedFile object
        
    Raises:
        FileValidationError: If file validation fails
    """
    is_valid, error_message = validate_file_type(uploaded_file)
    
    if not is_valid:
        raise FileValidationError(error_message)
