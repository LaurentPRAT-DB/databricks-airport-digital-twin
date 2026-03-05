"""Circuit breaker pattern for API failover."""

from datetime import datetime
from typing import Literal


class APICircuitBreaker:
    """
    Circuit breaker to prevent cascade failures when OpenSky API is unavailable.

    States:
    - closed: Normal operation, API calls allowed
    - open: API marked as down, all calls bypassed to fallback
    - half-open: After recovery_timeout, one test call allowed

    Usage:
        breaker = APICircuitBreaker(failure_threshold=5, recovery_timeout=60)

        if breaker.can_execute():
            try:
                result = api_call()
                breaker.record_success()
            except Exception:
                breaker.record_failure()
                result = fallback_data()
        else:
            result = fallback_data()
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of consecutive failures before opening circuit.
            recovery_timeout: Seconds to wait before attempting recovery (half-open).
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time: datetime | None = None
        self.state: Literal["closed", "open", "half-open"] = "closed"

    def record_failure(self) -> None:
        """
        Record an API failure.

        Increments failure counter. If threshold reached, transitions to open state.
        """
        self.failures += 1
        self.last_failure_time = datetime.utcnow()

        if self.failures >= self.failure_threshold:
            self.state = "open"

    def record_success(self) -> None:
        """
        Record a successful API call.

        Resets failure counter and transitions to closed state.
        """
        self.failures = 0
        self.state = "closed"

    def can_execute(self) -> bool:
        """
        Check if an API call should be attempted.

        Returns:
            True if circuit is closed, or if open and recovery_timeout has elapsed
            (transitions to half-open). False if circuit is open and still within timeout.
        """
        if self.state == "closed":
            return True

        if self.state == "open":
            if self.last_failure_time is None:
                return True

            elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
            if elapsed >= self.recovery_timeout:
                self.state = "half-open"
                return True
            return False

        # half-open: allow one test call
        return True


# Module-level singleton for shared state across imports
api_circuit_breaker = APICircuitBreaker()
