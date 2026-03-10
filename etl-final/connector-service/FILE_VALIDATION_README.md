# File Validation - Implementation Summary

## Overview
This document describes the file validation implementation for the connector service, addressing security requirements 1.1.4 and 1.1.5 from the ETL Architecture Redesign spec.

## Implementation Details

### Whitelist Approach
The implementation uses a strict whitelist of allowed file types:
- **CSV** (`.csv`)
- **Excel** (`.xls`, `.xlsx`)
- **Parquet** (`.parquet`)

### Validation Strategy
Three-level validation is performed:

1. **File Size Validation**: Checks if file size is within configured limits
   - Default limit: 1GB (1,073,741,824 bytes)
   - Configurable via `MAX_FILE_SIZE` environment variable
   - Rejects files exceeding the limit with human-readable error messages

2. **Extension Validation**: Checks if the file extension is in the whitelist
   - Case-insensitive comparison
   - Extracts extension from filename
   - Rejects files without extensions

3. **MIME Type Validation**: Verifies MIME type matches expected types for the extension
   - Only performed if MIME type is available
   - Detects spoofed files (e.g., `.csv` extension with PDF MIME type)
   - Handles multiple valid MIME types per extension

### Configuration

#### File Size Limit
The maximum file size can be configured via environment variable:

```bash
# Set custom limit (e.g., 500MB)
export MAX_FILE_SIZE=524288000

# Use default (1GB) if not set
# MAX_FILE_SIZE=1073741824
```

The limit is defined in `connector/settings.py`:
```python
MAX_FILE_SIZE = int(os.environ.get('MAX_FILE_SIZE', 1073741824))  # Default: 1GB
```

### Files Created/Modified

#### 1. `file_validator.py`
Core validation module containing:
- `validate_file_type()`: Main validation function returning (is_valid, error_message)
- `validate_file_or_raise()`: Validation function that raises FileValidationError
- `get_file_extension()`: Helper to extract and normalize file extensions
- `get_max_file_size()`: Retrieves configured maximum file size
- `format_file_size()`: Formats file sizes in human-readable format (KB, MB, GB)
- `FileValidationError`: Custom exception for validation failures

#### 2. `test_file_validator.py`
Comprehensive unit tests covering:
- File size validation (10 test cases)
- Extension validation (29 test cases)
- MIME type validation
- Security scenarios (executable files, scripts, zip files)
- Edge cases (no extension, case sensitivity, multiple dots)
- Human-readable error messages

#### 3. `test_file_upload_validation.py`
Integration tests for the upload endpoint:
- Valid file uploads (CSV, Excel, Parquet)
- Invalid file rejections (TXT, JSON, PDF, EXE)
- MIME type mismatch detection
- Error message validation

#### 4. `connector/settings.py`
Added configuration:
- `MAX_FILE_SIZE`: Configurable file size limit (default 1GB)

### Integration with Views

The `UploadFileView` in `views.py` validates files **before** saving to disk:
1. Validate file size against configured limit
2. Validate file type against whitelist
3. Validate MIME type (if available)
4. Return 400 Bad Request with descriptive error message if validation fails
5. Only proceed with file storage and Kafka publishing if validation passes

```python
# Validate file type and size (whitelist: CSV, Excel, Parquet; max: 1GB)
is_valid, error_message = validate_file_type(uploaded_file)
if not is_valid:
    return Response(make_response(False, error_message), status=400)
```

## Security Benefits

1. **Prevents Large File DoS**: Rejects files exceeding size limit before processing
2. **Prevents Malicious Uploads**: Rejects executable files, scripts, and other dangerous file types
3. **Spoofing Detection**: MIME type validation catches files with fake extensions
4. **Clear Error Messages**: Users are informed of allowed file types and size limits
5. **Fail-Fast**: Validation occurs before file is written to disk

## Testing

Run unit tests:
```bash
cd etl-final/connector-service/connector
python -m unittest etl_engine.test_file_validator -v
```

Run integration tests:
```bash
python manage.py test etl_engine.test_file_upload_validation
```

## Example Usage

### Valid Upload (Within Size Limit)
```bash
curl -X POST http://localhost:8001/upload/ \
  -F "file=@data.csv"
```

Response:
```json
{
  "success": true,
  "message": "File uploaded successfully",
  "data": {
    "saved_path": "/app/uploaded_files/uuid_data.csv"
  }
}
```

### Invalid Upload (File Too Large)
```bash
curl -X POST http://localhost:8001/upload/ \
  -F "file=@huge_file.csv"
```

Response:
```json
{
  "success": false,
  "message": "File size 2.50 GB exceeds maximum allowed size of 1.00 GB"
}
```

### Invalid Upload (Wrong File Type)
```bash
curl -X POST http://localhost:8001/upload/ \
  -F "file=@document.pdf"
```

Response:
```json
{
  "success": false,
  "message": "File type '.pdf' not allowed. Allowed types: .csv, .parquet, .xls, .xlsx"
}
```

## Configuration Examples

### Development Environment (Allow Larger Files)
```bash
# Allow 5GB files
export MAX_FILE_SIZE=5368709120
```

### Production Environment (Stricter Limits)
```bash
# Limit to 500MB
export MAX_FILE_SIZE=524288000
```

### Docker Compose
```yaml
services:
  connector-service:
    environment:
      - MAX_FILE_SIZE=1073741824  # 1GB
```

## Future Enhancements

Potential improvements for future phases:
- Virus scanning integration (Task 1.1.6)
- Content-based validation (magic bytes)
- Rate limiting per user/IP (Task 1.2.3)
- Streaming validation for very large files
- Configurable whitelist via environment variables

## Related Tasks

- ✅ Task 1.1.4: Add file type validation (COMPLETED)
- ✅ Task 1.1.5: Implement file size limits (COMPLETED)
- ⏳ Task 1.1.6: Add virus scanning integration
