"""Network destination policy for user supplied database connections."""

from dataclasses import dataclass
import ipaddress
import os
import socket


class DestinationPolicyError(ValueError):
    pass


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
    return any(address.version == network.version and address in network for network in networks)


def _is_forbidden(address) -> bool:
    return any((
        address.is_loopback,
        address.is_link_local,
        address.is_private,
        address.is_multicast,
        address.is_reserved,
        address.is_unspecified,
    ))


def validate_destination(host: str, port: int):
    """Resolve every address and reject the destination if any result violates policy."""

    try:
        resolved = socket.getaddrinfo(host, int(port), type=socket.SOCK_STREAM)
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
