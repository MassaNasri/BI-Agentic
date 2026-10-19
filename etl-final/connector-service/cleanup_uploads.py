"""Delete abandoned private upload staging files after the one-day TTL."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'connector'))

from etl_engine.file_storage import cleanup_expired_uploads


if __name__ == '__main__':
    print(f'expired_uploads_removed={cleanup_expired_uploads()}')
