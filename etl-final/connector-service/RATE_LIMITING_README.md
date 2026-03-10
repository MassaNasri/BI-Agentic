# Rate Limiting Implementation

## Overview

The connector service implements comprehensive rate limiting to prevent abuse and ensure fair resource allocation. Rate limiting is applied per IP address and per authenticated user using a sliding window algorithm.

## Features

### 1. Per-IP Rate Limiting
- Limits requests from individual IP addresses
- Prevents DoS attacks from single sources
- Default: 100 requests per 60 seconds

### 2. Per-User Rate Limiting
- Higher limits for authenticated users
- Independent from IP-based limits
- Default: 200 requests per 60 seconds

### 3. Sliding Window Algorithm
- More accurate than fixed window approach
- Prevents burst attacks at window boundaries
- Smooth rate limiting over time

### 4. Proxy Support
- Respects `X-Forwarded-For` header
- Correctly identifies client IP behind proxies
- Takes first IP in forwarded chain

### 5. Thread-Safe Implementation
- Safe for concurrent requests
- Uses locks to prevent race conditions
- Automatic cleanup of old entries

### 6. Comprehensive Monitoring
- Tracks total requests
- Counts rate-limited requests
- Monitors unique IPs and users
- Calculates rate limit percentage

## Configuration

Rate limiting is configured via environment variables in `settings.py`:

```python
# Enable/disable rate limiting
RATE_LIMIT_ENABLED = True  # Set to False to disable

# Per-IP rate limiting
RATE_LIMIT_REQUESTS = 100  # Max requests per window (per IP)
RATE_LIMIT_WINDOW = 60     # Time window in seconds

# Per-user rate limiting (for authenticated users)
RATE_LIMIT_PER_USER_REQUESTS = 200  # Max requests per window (per user)
```

### Environment Variables

```bash
# Rate limiting configuration
RATE_LIMIT_ENABLED=True
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60
RATE_LIMIT_PER_USER_REQUESTS=200
```

## Response Headers

### Successful Requests

All successful requests include rate limit headers:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1234567890
```

- `X-RateLimit-Limit`: Maximum requests allowed in window
- `X-RateLimit-Remaining`: Requests remaining in current window
- `X-RateLimit-Reset`: Unix timestamp when limit resets

### Rate-Limited Requests

When rate limit is exceeded, the response includes:

```
HTTP/1.1 429 Too Many Requests
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1234567890
Retry-After: 60
```

Response body:
```json
{
  "success": false,
  "message": "Rate limit exceeded. Maximum 100 requests per 60 seconds.",
  "correlation_id": "abc-123-def",
  "retry_after": 60
}
```

## Implementation Details

### Middleware Architecture

Rate limiting is implemented as Django middleware in `middleware.py`:

```python
MIDDLEWARE = [
    # ... other middleware ...
    'etl_engine.middleware.RateLimitMiddleware',
    # ... other middleware ...
]
```

### Sliding Window Algorithm

The sliding window algorithm works as follows:

1. Each request is timestamped and stored
2. On new request, old timestamps outside the window are removed
3. Current count is compared against limit
4. If limit exceeded, request is rejected
5. Otherwise, request is recorded and allowed

Example:
```
Window: 60 seconds, Limit: 5 requests

Time 0s:  Request 1 ✓ (count: 1)
Time 10s: Request 2 ✓ (count: 2)
Time 20s: Request 3 ✓ (count: 3)
Time 30s: Request 4 ✓ (count: 4)
Time 40s: Request 5 ✓ (count: 5)
Time 50s: Request 6 ✗ (count: 5, limit exceeded)
Time 65s: Request 7 ✓ (count: 4, request 1 expired)
```

### Memory Management

To prevent unbounded memory growth:

- Old entries are automatically cleaned up
- Cleanup triggers after 1000 unique identifiers
- Removes identifiers with no recent requests
- Maintains O(n) memory where n = active clients

### Thread Safety

Thread safety is ensured through:

- `threading.Lock` for request_counts dictionary
- Separate lock for statistics
- Atomic operations within lock context
- No shared mutable state outside locks

## Testing

### Unit Tests

Comprehensive unit tests are provided in `test_rate_limiting_standalone.py`:

```bash
# Run standalone tests (no Django dependencies)
python test_rate_limiting_standalone.py
```

Test coverage includes:
- ✓ Per-IP rate limiting
- ✓ Per-user rate limiting
- ✓ Different IPs have independent limits
- ✓ X-Forwarded-For header support
- ✓ Sliding window algorithm
- ✓ Rate limit can be disabled
- ✓ Statistics tracking
- ✓ Thread safety (concurrent requests)

### Integration Tests

Integration tests in `test_rate_limiting.py` test with full Django setup:

```bash
# Run Django integration tests
python run_rate_limiting_tests.py
```

## Usage Examples

### Example 1: Normal Usage

```bash
# First request - succeeds
curl -X POST http://localhost:8001/api/upload/ \
  -F "file=@data.csv"

# Response includes rate limit headers
# X-RateLimit-Limit: 100
# X-RateLimit-Remaining: 99
```

### Example 2: Rate Limit Exceeded

```bash
# After 100 requests in 60 seconds
curl -X POST http://localhost:8001/api/upload/ \
  -F "file=@data.csv"

# Response: 429 Too Many Requests
# {
#   "success": false,
#   "message": "Rate limit exceeded. Maximum 100 requests per 60 seconds.",
#   "retry_after": 60
# }
```

### Example 3: Behind Proxy

```bash
# Request through proxy with X-Forwarded-For
curl -X POST http://localhost:8001/api/upload/ \
  -H "X-Forwarded-For: 10.0.0.1, 192.168.1.1" \
  -F "file=@data.csv"

# Rate limiting uses first IP: 10.0.0.1
```

## Monitoring

### Statistics API

Get rate limiting statistics:

```python
from etl_engine.middleware import RateLimitMiddleware

# Access middleware instance
middleware = RateLimitMiddleware(get_response)

# Get statistics
stats = middleware.get_stats()
# {
#   'total_requests': 1000,
#   'rate_limited_requests': 50,
#   'unique_ips': 25,
#   'unique_users': 10,
#   'rate_limit_percentage': 5.0
# }
```

### Logging

Rate limiting events are logged with correlation IDs:

```
[INFO] [abc-123] Incoming request: POST /api/upload/
[WARNING] [abc-123] Rate limit exceeded for IP: 192.168.1.1
```

## Production Considerations

### Single Instance Deployment

The current implementation uses in-memory storage, suitable for:
- Single-instance deployments
- Development environments
- Small-scale production (< 1000 req/s)

### Multi-Instance Deployment

For production with multiple instances, consider:

1. **Redis-based rate limiting**
   - Shared state across instances
   - Atomic operations with Redis
   - Better scalability

2. **API Gateway rate limiting**
   - Nginx rate limiting module
   - AWS API Gateway
   - Kong or similar

3. **Distributed rate limiting**
   - Token bucket algorithm
   - Consistent hashing
   - Distributed counters

### Recommended Settings

**Development:**
```bash
RATE_LIMIT_ENABLED=True
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60
```

**Production (light load):**
```bash
RATE_LIMIT_ENABLED=True
RATE_LIMIT_REQUESTS=1000
RATE_LIMIT_WINDOW=60
```

**Production (heavy load):**
```bash
RATE_LIMIT_ENABLED=True
RATE_LIMIT_REQUESTS=10000
RATE_LIMIT_WINDOW=60
```

## Security Benefits

1. **DoS Prevention**: Prevents single IP from overwhelming service
2. **Brute Force Protection**: Limits password guessing attempts
3. **Resource Protection**: Ensures fair resource allocation
4. **Cost Control**: Prevents excessive API usage
5. **Abuse Prevention**: Deters malicious actors

## Compliance

Rate limiting helps meet security requirements:

- **NFR-4 (Security)**: Prevents abuse and DoS attacks
- **US-9 (Observability)**: Provides metrics and monitoring
- **AC 1.2.3**: Implements per-user/IP rate limiting

## Troubleshooting

### Issue: Legitimate users being rate limited

**Solution**: Increase limits or window size
```bash
RATE_LIMIT_REQUESTS=200
RATE_LIMIT_WINDOW=60
```

### Issue: Rate limiting not working

**Check**:
1. Middleware is registered in settings
2. `RATE_LIMIT_ENABLED=True`
3. Requests include proper IP headers

### Issue: Memory growth

**Solution**: Automatic cleanup runs after 1000 identifiers. For more aggressive cleanup, modify `_cleanup_old_entries()` threshold.

## Future Enhancements

1. **Redis backend**: For multi-instance deployments
2. **Per-endpoint limits**: Different limits for different endpoints
3. **Dynamic limits**: Adjust limits based on load
4. **Whitelist/blacklist**: IP-based access control
5. **Rate limit bypass**: For trusted clients
6. **Burst allowance**: Allow short bursts above limit

## References

- [RFC 6585 - HTTP Status Code 429](https://tools.ietf.org/html/rfc6585)
- [IETF Draft - RateLimit Header Fields](https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-ratelimit-headers)
- [OWASP - Denial of Service](https://owasp.org/www-community/attacks/Denial_of_Service)
