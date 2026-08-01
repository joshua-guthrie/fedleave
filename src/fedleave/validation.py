"""Validate and normalize untrusted text before it reaches stored data."""

from __future__ import annotations

from urllib.parse import urlparse


def sanitize_text(value: str, *, field_name: str = "value", max_length: int = 1024) -> str:
    """Reject unsafe or oversized text and strip surrounding whitespace."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if "\x00" in value:
        raise ValueError(f"{field_name} contains null byte which is not allowed")
    if len(value) > max_length:
        raise ValueError(f"{field_name} too long (max {max_length} characters)")
    return value.strip()


def sanitize_url(value: str, *, field_name: str = "url") -> str:
    """Return a sanitized HTTP(S) URL with a nonempty host."""
    s = sanitize_text(value, field_name=field_name, max_length=2048)
    parsed = urlparse(s)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"{field_name} must be an http(s) URL")
    if not parsed.netloc:
        raise ValueError(f"{field_name} missing host")
    return s
