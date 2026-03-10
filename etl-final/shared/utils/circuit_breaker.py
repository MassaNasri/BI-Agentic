"""
Simple circuit breaker implementation.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class CircuitBreakerState:
    failures: int = 0
    opened_at: float = 0.0


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_time: int = 30):
        self.failure_threshold = failure_threshold
        self.recovery_time = recovery_time
        self.state = CircuitBreakerState()

    def allow(self) -> bool:
        if self.state.failures < self.failure_threshold:
            return True
        if (time.time() - self.state.opened_at) > self.recovery_time:
            self.state.failures = 0
            self.state.opened_at = 0.0
            return True
        return False

    def record_success(self) -> None:
        self.state.failures = 0
        self.state.opened_at = 0.0

    def record_failure(self) -> None:
        self.state.failures += 1
        if self.state.failures >= self.failure_threshold:
            self.state.opened_at = time.time()
