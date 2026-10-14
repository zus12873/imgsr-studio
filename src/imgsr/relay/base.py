from __future__ import annotations


def normalize_base(url: str) -> str:
    url = url.rstrip("/")
    return url[:-3] if url.endswith("/v1") else url


def masked(key: str) -> str:
    return f"{key[:6]}…{key[-4:]}" if len(key) > 12 else "***"
