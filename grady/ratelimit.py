"""A simple rate limiter: makes sure calls are at least N seconds apart."""

import time


class RateLimiter:
    def __init__(self, min_interval_seconds: float):
        self.min_interval = min_interval_seconds
        self._last_call = None  # time.monotonic() of the previous call

    def wait(self) -> None:
        """Sleep just long enough to keep calls min_interval apart, then record this call."""
        if self._last_call is not None:
            elapsed = time.monotonic() - self._last_call
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()
