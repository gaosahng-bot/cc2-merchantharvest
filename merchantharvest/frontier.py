"""Checkpointable URL frontier with volatile-query canonicalization."""
from __future__ import annotations

from collections import deque
from urllib.parse import urlparse, urlunparse, urlencode, parse_qsl, urljoin

VOLATILE_PARAMS = {"session"}


def canonicalize_url(url: str, base: str | None = None) -> str:
    """Resolve relative URLs and drop utm_* / session query parameters."""
    if base is not None:
        url = urljoin(base, url)
    parts = urlparse(url)
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.startswith("utm_") and key not in VOLATILE_PARAMS
    ]
    query = urlencode(kept)
    path = parts.path or "/"
    return urlunparse((parts.scheme, parts.netloc, path, parts.params, query, ""))


class Frontier:
    """FIFO frontier keyed by canonical URL; safe to dump/load for checkpoints."""

    def __init__(self, base: str | None = None) -> None:
        self.base = base
        self._queue: deque[str] = deque()
        self._seen: set[str] = set()

    def canonicalize(self, url: str) -> str:
        return canonicalize_url(url, self.base)

    def push(self, url: str) -> bool:
        """Enqueue a URL. Returns False when its canonical form was already seen."""
        canonical = self.canonicalize(url)
        if canonical in self._seen:
            return False
        self._seen.add(canonical)
        self._queue.append(canonical)
        return True

    def pop(self) -> str | None:
        if not self._queue:
            return None
        return self._queue.popleft()

    def __len__(self) -> int:
        return len(self._queue)

    @property
    def seen(self) -> set[str]:
        return set(self._seen)

    def dump(self) -> dict:
        return {"base": self.base, "queue": list(self._queue), "seen": sorted(self._seen)}

    def load(self, data: dict) -> None:
        self.base = data.get("base")
        self._queue = deque(data.get("queue", []))
        self._seen = set(data.get("seen", []))
