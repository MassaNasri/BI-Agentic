"""Network destination policy for user supplied database connections."""

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, TimeoutError as ResolverTimeout
import ipaddress
import os
import socket
import threading


class DestinationPolicyError(ValueError):
    pass


_DNS_WORKERS = ThreadPoolExecutor(max_workers=4, thread_name_prefix="source-dns")
_DNS_SLOTS = threading.BoundedSemaphore(4)


def _approved_networks():
    configured = os.getenv("ETL_APPROVED_DESTINATION_CIDRS", "")
    networks = []
    for value in configured.split(","):
        value = value.strip()
        if value:
            try:
                networks.append(ipaddress.ip_network(value, strict=False))
            except ValueError as exc:
                raise DestinationPolicyError("ETL destination allowlist contains an invalid CIDR.") from exc
    return tuple(networks)


def _is_explicitly_approved(address, networks) -> bool:
    if os.getenv("APP_ENV") == "production":
        return False
    return any(address.version == network.version and address in network for network in networks)


def _is_forbidden(address) -> bool:
    return any((
        address.is_loopback,
        address.is_link_local,
        address.is_private,
        address.is_multicast,
        address.is_reserved,
        address.is_unspecified,
        not address.is_global,
    ))


def validate_destination(host: str, port: int):
    """Resolve every address and reject the destination if any result violates policy."""

    try:
        port = int(port)
        if not 1 <= port <= 65535:
            raise ValueError
        if not _DNS_SLOTS.acquire(timeout=3):
            raise ResolverTimeout()
        try:
            future = _DNS_WORKERS.submit(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
        except Exception:
            _DNS_SLOTS.release()
            raise
        future.add_done_callback(lambda _future: _DNS_SLOTS.release())
        resolved = future.result(timeout=3)
    except ResolverTimeout as exc:
        raise DestinationPolicyError("Database destination could not be resolved within the time limit.") from exc
    except (socket.gaierror, OSError, TypeError, ValueError) as exc:
        raise DestinationPolicyError("Database destination could not be resolved.") from exc
    addresses = {ipaddress.ip_address(item[4][0]) for item in resolved}
    if not addresses:
        raise DestinationPolicyError("Database destination resolved to no addresses.")
    allowlist = _approved_networks()
    denied = [address for address in addresses if _is_forbidden(address) and not _is_explicitly_approved(address, allowlist)]
    if denied:
        raise DestinationPolicyError("Database destination is not allowed by network policy.")
    return tuple(sorted(str(address) for address in addresses))
