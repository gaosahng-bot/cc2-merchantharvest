"""URL frontier + checkpoint — NOT implemented yet."""
from __future__ import annotations


class Frontier:
    def __init__(self) -> None:
        pass

    def push(self, url: str) -> None:
        raise NotImplementedError

    def pop(self) -> str | None:
        raise NotImplementedError

    def canonicalize(self, url: str) -> str:
        """Drop utm_* and session query parameters, keep the rest, normalize."""
        raise NotImplementedError

    def dump(self) -> dict:
        raise NotImplementedError

    def load(self, data: dict) -> None:
        raise NotImplementedError
