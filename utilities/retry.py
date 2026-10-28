from __future__ import annotations
import time
from functools import wraps

def retry(attempts: int = 5, backoff_seconds: float = 2.0):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last = None
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last = exc
                    if attempt >= attempts:
                        raise
                    time.sleep(backoff_seconds * (2 ** (attempt - 1)))
            raise last
        return wrapper
    return decorator
