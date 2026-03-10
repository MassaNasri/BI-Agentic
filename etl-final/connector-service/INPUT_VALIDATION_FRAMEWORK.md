# Input Validation Framework

## Overview

Comprehensive input validation framework for all API endpoints in the ETL pipeline. Provides declarative validation rules, security-focused sanitization, and protection against common attacks.

## Features

- **Declarative Validation**: Define validation rules in a clear, readable format
- **Type Safety**: Validate data types, ranges, patterns, and enums
- **Security**: Prevent SQL injection, XSS, null byte injection, and other attacks
- **Sanitization**: Automatic input sanitization to remove malicious content
- **Rate Limiting**: Protect against DoS attacks with configurable rate limits
- **Request Size Limits**: Prevent memory exhaustion from large payloads
- **Correlation IDs**: Track requests across services for debugging
- **Comprehensive Error Messages**: Clear, actionable error messages for clients

## Architecture

### Components

1. **FieldValidator**: Validates individual fields with multiple rules
2. **RequestValidator**: Combines field validators for entire requests
3. **Common Validators**: Pre-built validators for common patterns (ports, hostnames, etc.)
4. **Sanitization Functions**: Clean inputs to prevent injection attacks
5. **Middleware**: Global request validation, rate limiting, and security headers

### Validation Flow

```
Request → Middleware (size, rate limit) → View (field validation) → Sanitization → Business Logic
```

## Usage

### Basic Field Validation

```python
from shared.utils.input_validator import FieldValidator

# Create a validator for a required string field
validator = FieldValidator("username", required=True).type(str).min_length(3).max_length(20)

# Validate data
is_valid, error = validator.validate({"username": "john_doe"})
if not is_valid:
    print(f"Validation error: {error}")
```

### Request Validation

```python
from shared.utils.input_validator import RequestValidator, FieldValidator

# Create a request validator
validator = RequestValidator()
validator.add_field(FieldValidator("name", required=True).type(str))
validator.add_field(FieldValidator("age", required=True).type(int).min_value(0))

# Validate entire request
is_valid, errors = validator.validate(request.data)
if not is_valid:
    return Response({"errors": errors}, status=400)
```

### Pre-built Validators

```python
from shared.utils.input_validator import create_db_connection_validator

# Use pre-built validator for database connections
validator = create_db_connection_validator()
is_valid, errors = validator.validate(request.data)
```

### Custom Validators

```python
from shared.utils.input_validator import FieldValidator

def validate_even_number(value):
    """Custom validator for even numbers."""
    if value % 2 == 0:
        return True, ""
    return False, "Value must be even"

validator = FieldValidator("number").custom(validate_even_number)
```

### Sanitization

```python
from shared.utils.input_validator import sanitize_string

# Sanitize user input
clean_input = sanitize_string(user_input, max_length=1000)
```

## Validation Rules

### Available Rules

| Rule | Description | Example |
|------|-------------|---------|
| `required` | Field must be present and non-empty | `FieldValidator("name", required=True)` |
| `type` | Field must be of specific type | `.type(str)` |
| `min_length` | Minimum string/list length | `.min_length(8)` |
| `max_length` | Maximum string/list length | `.max_length(100)` |
| `min_value` | Minimum numeric value | `.min_value(0)` |
| `max_value` | Maximum numeric value | `.max_value(100)` |
| `pattern` | Match regex pattern | `.pattern(r'^[a-zA-Z0-9]+$')` |
| `enum` | Value must be in list | `.enum(["active", "inactive"])` |
| `custom` | Custom validation function | `.custom(my_validator)` |

### Chaining Rules

Rules can be chained together for comprehensive validation:

```python
validator = (
    FieldValidator("password", required=True)
    .type(str)
    .min_length(8)
    .max_length(128)
    .pattern(r'^(?=.*[A-Z])(?=.*[a-z])(?=.*\d).*$')  # At least one uppercase, lowercase, digit
)
```

## Common Validators

### Port Validation

```python
from shared.utils.input_validator import validate_port

is_valid, error = validate_port(3306)  # Returns (True, "")
is_valid, error = validate_port(99999)  # Returns (False, "Port must be between 1 and 65535")
```

### Hostname Validation

```python
from shared.utils.input_validator import validate_hostname

is_valid, error = validate_hostname("localhost")  # Returns (True, "")
is_valid, error = validate_hostname("invalid..hostname")  # Returns (False, "Invalid hostname format")
```

### Database Name Validation

```python
from shared.utils.input_validator import validate_database_name

is_valid, error = validate_database_name("my_database")  # Returns (True, "")
is_valid, error = validate_database_name("db; DROP TABLE")  # Returns (False, "Database name can only contain...")
```

### Username Validation

```python
from shared.utils.input_validator import validate_username

is_valid, error = validate_username("john_doe")  # Returns (True, "")
is_valid, error = validate_username("john; DROP")  # Returns (False, "Username contains invalid characters")
```

## Middleware

### Request Validation Middleware

Validates request size and adds correlation IDs:

```python
# Configured in settings.py
MAX_REQUEST_SIZE = 10485760  # 10MB
```

Features:
- Request size validation
- Correlation ID generation and tracking
- Request/response logging

### Rate Limit Middleware

Protects against DoS attacks:

```python
# Configured in settings.py
RATE_LIMIT_ENABLED = True
RATE_LIMIT_REQUESTS = 100  # requests per window
RATE_LIMIT_WINDOW = 60  # seconds
```

Features:
- Per-IP rate limiting
- Configurable limits
- Automatic cleanup of old entries

### Security Headers Middleware

Adds security headers to all responses:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Content-Security-Policy: default-src 'self'`

## Configuration

### Environment Variables

```bash
# File validation
MAX_FILE_SIZE=1073741824  # 1GB

# Request validation
MAX_REQUEST_SIZE=10485760  # 10MB

# Rate limiting
RATE_LIMIT_ENABLED=True
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60
```

### Django Settings

```python
# connector/connector/settings.py

# Input validation settings
MAX_REQUEST_SIZE = int(os.environ.get('MAX_REQUEST_SIZE', 10485760))

# Rate limiting settings
RATE_LIMIT_ENABLED = os.environ.get('RATE_LIMIT_ENABLED', 'True').lower() in ('true', '1', 'yes')
RATE_LIMIT_REQUESTS = int(os.environ.get('RATE_LIMIT_REQUESTS', 100))
RATE_LIMIT_WINDOW = int(os.environ.get('RATE_LIMIT_WINDOW', 60))

# Middleware
MIDDLEWARE = [
    # ... other middleware ...
    'etl_engine.middleware.RequestValidationMiddleware',
    'etl_engine.middleware.RateLimitMiddleware',
    'etl_engine.middleware.SecurityHeadersMiddleware',
]
```

## API Endpoint Integration

### ConnectDB Endpoint

The `/api/connect-db/` endpoint validates:

- **db_type**: Must be one of: mysql, postgresql, sqlite, mssql, oracle
- **host**: Valid hostname or IP address
- **port**: Valid port number (1-65535)
- **user**: Valid username (alphanumeric, underscores, dots, hyphens, @)
- **password**: Required, 1-256 characters
- **database**: Valid database name (alphanumeric, underscores, hyphens only)

Example valid request:

```json
{
  "db_type": "mysql",
  "host": "localhost",
  "port": 3306,
  "user": "root",
  "password": "secure_password",
  "database": "my_database"
}
```

Example error response:

```json
{
  "success": false,
  "message": "Field 'port' must be between 1 and 65535; Field 'database' can only contain letters, numbers, underscores, and hyphens"
}
```

### UploadFile Endpoint

The `/api/upload/` endpoint validates:

- File presence
- File type (CSV, Excel, Parquet)
- File size (configurable, default 1GB)
- MIME type matching
- Virus scanning (if enabled)

## Security Features

### SQL Injection Prevention

- Database names validated with strict character whitelist
- Usernames validated with safe character set
- Hostnames validated with proper format
- All inputs sanitized before use

### XSS Prevention

- String sanitization removes null bytes
- Security headers prevent XSS attacks
- Content-Type validation

### DoS Prevention

- Request size limits
- Rate limiting per IP
- Configurable thresholds

### Injection Attack Prevention

- Null byte removal
- Special character validation
- Pattern matching for safe inputs

## Testing

### Unit Tests

```bash
cd etl-final/shared/utils
python -m unittest test_input_validator.py -v
```

### Integration Tests

```bash
cd etl-final/connector-service/connector
python manage.py test etl_engine.test_api_validation
```

## Error Handling

### Validation Errors

Validation errors return HTTP 400 with detailed error messages:

```json
{
  "success": false,
  "message": "Field 'username' is required; Field 'age' must be at least 0"
}
```

### Rate Limit Errors

Rate limit exceeded returns HTTP 429:

```json
{
  "success": false,
  "message": "Rate limit exceeded. Maximum 100 requests per 60 seconds.",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Request Size Errors

Oversized requests return HTTP 413:

```json
{
  "success": false,
  "message": "Request size 15.50MB exceeds maximum allowed size of 10.00MB",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

## Best Practices

1. **Always validate at the API boundary**: Don't trust client input
2. **Use pre-built validators**: Leverage common validators for consistency
3. **Sanitize after validation**: Clean inputs even after validation
4. **Log validation failures**: Track suspicious patterns
5. **Provide clear error messages**: Help clients fix issues
6. **Test edge cases**: Include injection attempts in tests
7. **Configure limits appropriately**: Balance security and usability
8. **Monitor rate limits**: Track and alert on rate limit hits

## Extending the Framework

### Adding New Validators

```python
# In shared/utils/input_validator.py

def validate_custom_format(value: str) -> Tuple[bool, str]:
    """Validate custom format."""
    if not value or not isinstance(value, str):
        return False, "Value must be a non-empty string"
    
    # Your validation logic here
    if is_valid(value):
        return True, ""
    
    return False, "Invalid format"
```

### Creating Pre-built Validators

```python
def create_my_endpoint_validator() -> RequestValidator:
    """Create validator for my endpoint."""
    validator = RequestValidator()
    
    validator.add_field(
        FieldValidator("field1", required=True)
        .type(str)
        .min_length(1)
    )
    
    validator.add_field(
        FieldValidator("field2", required=False)
        .type(int)
        .min_value(0)
    )
    
    return validator
```

## Performance Considerations

- **Validation overhead**: ~1-5ms per request (negligible)
- **Rate limiting**: In-memory storage, O(1) lookup
- **Sanitization**: O(n) where n is string length
- **Memory usage**: Minimal, ~1KB per validator instance

## Future Enhancements

- [ ] Redis-based rate limiting for distributed systems
- [ ] Schema validation with JSON Schema
- [ ] OpenAPI/Swagger integration
- [ ] Validation metrics and monitoring
- [ ] Custom error message templates
- [ ] Validation rule versioning
- [ ] Async validation support

## References

- [OWASP Input Validation Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html)
- [Django Security Best Practices](https://docs.djangoproject.com/en/stable/topics/security/)
- [REST API Security Best Practices](https://restfulapi.net/security-essentials/)

## Support

For issues or questions:
1. Check the test files for examples
2. Review the inline documentation
3. Consult the design document: `.kiro/specs/etl-architecture-redesign/design.md`
