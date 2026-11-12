"""Politeness / crawl-delay — NOT implemented yet."""
from __future__ import annotations


class Politeness:
    def __init__(self, robots_txt: str) -> None:
        self.robots_txt = robots_txt

    def delay_s(self, user_agent: str = "*") -> float:
        raise NotImplementedError("parse Crawl-delay and honour it")

    def wait(self, host: str) -> None:
        """Block until the host may be hit again."""
        raise NotImplementedError
