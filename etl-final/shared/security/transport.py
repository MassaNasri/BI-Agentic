"""Network reachability is independent of database engine protocol."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import os

from shared.security.destination_policy import DestinationPolicyError, validate_destination


@dataclass(frozen=True)
class ConnectionTarget:
    hostname: str
    address: str
    port: int


class ConnectionTransport(ABC):
    @abstractmethod
    def before_connect(self, configuration, engine):
        """Return a validated, pinned target for the next driver connection."""


class DirectSecureInternetTransport(ConnectionTransport):
    mode = "direct_secure_internet"
    _pinned_and_tls_verified = frozenset({"postgres", "clickhouse"})

    def before_connect(self, configuration, engine):
        hostname = str(configuration.get("host") or "").strip()
        try:
            port = int(configuration.get("port"))
        except (TypeError, ValueError) as exc:
            raise DestinationPolicyError("Database port is invalid.") from exc
        if not hostname or not 1 <= port <= 65535:
            raise DestinationPolicyError("Database destination is invalid.")
        if os.getenv("APP_ENV") == "production":
            if engine not in self._pinned_and_tls_verified:
                raise DestinationPolicyError("This engine is not certified for direct production transport.")
            if engine == "postgres" and configuration.get("sslmode", "verify-full") != "verify-full":
                raise DestinationPolicyError("Verified source TLS is required.")
            if engine == "clickhouse" and (configuration.get("secure") is not True or configuration.get("verify") is not True):
                raise DestinationPolicyError("Verified source TLS is required.")
        # Called immediately before the driver opens its socket. Every answer is
        # checked again; the driver receives only this validated numeric address.
        addresses = validate_destination(hostname, port)
        return ConnectionTarget(hostname, addresses[0], port)


def get_transport(mode):
    if mode in (None, "direct_secure_internet"):
        return DirectSecureInternetTransport()
    raise DestinationPolicyError("Source transport is unavailable.")
