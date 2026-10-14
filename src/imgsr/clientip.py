"""Resolve the real client IP behind trusted reverse proxies."""

from __future__ import annotations

from collections.abc import Mapping
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network

Network = IPv4Network | IPv6Network


def parse_networks(spec: str) -> list[Network]:
    return [ip_network(part.strip(), strict=False) for part in spec.split(",") if part.strip()]


def _is_trusted(addr: str, trusted: list[Network]) -> bool:
    try:
        ip = ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in trusted)


def resolve_client_ip(
    peer: str, headers: Mapping[str, str], header_name: str, trusted: list[Network]
) -> str:
    """Only trust `header_name` when the TCP peer is a trusted proxy; walk XFF from the right."""
    if not _is_trusted(peer, trusted):
        return peer
    raw = headers.get(header_name)
    if not raw:
        return peer
    candidates = [part.strip() for part in raw.split(",") if part.strip()]
    for candidate in reversed(candidates):
        try:
            ip_address(candidate)
        except ValueError:
            return peer
        if not _is_trusted(candidate, trusted):
            return candidate
    return candidates[0] if candidates else peer
