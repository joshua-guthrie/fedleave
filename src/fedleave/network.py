"""Byte budgets for the application's small network documents."""


def read_bounded(response, limit: int) -> bytes:
    """Bound actual bytes, even when Content-Length is missing or misleading."""
    parts = []
    size = 0
    while True:
        block = response.read(min(65536, limit + 1 - size))
        if not block:
            return b"".join(parts)
        size += len(block)
        if size > limit:
            raise ValueError(f"Network document exceeds the {limit}-byte limit")
        parts.append(block)
