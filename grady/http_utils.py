"""HTTP helper shared by all job sources: rate limiting and retries."""

import time

import requests

from grady.ratelimit import RateLimiter

TIMEOUT_SECONDS = 30

# Retry "too many requests" (429) and server errors (5xx), which are usually
# temporary. Other errors, like a wrong API key (401), won't fix themselves.
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 5  # wait 5s, then 10s


class ApiError(Exception):
    pass


def get_with_retries(
    url: str,
    params: dict,
    rate_limiter: RateLimiter,
    description: str,
    auth: tuple[str, str] | None = None,
) -> requests.Response:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        rate_limiter.wait()
        response = requests.get(url, params=params, auth=auth, timeout=TIMEOUT_SECONDS)
        if response.status_code == 200:
            return response

        # Don't use response.raise_for_status(): its error message includes the full
        # URL, which can contain an API key, and that would end up in logs.
        retryable = response.status_code == 429 or response.status_code >= 500
        if not retryable or attempt == MAX_ATTEMPTS:
            raise ApiError(f"HTTP {response.status_code} for {description}")

        # Exponential backoff: wait longer after each failed attempt.
        time.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
