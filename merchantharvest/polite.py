"""Robots.txt parsing and per-host crawl-delay throttling."""
from __future__ import annotations

import threading
import time
from urllib.parse import urlparse


class RobotsRules:
    """Minimal robots.txt: collects Disallow paths and Crawl-delay per agent group."""

    def __init__(self, robots_txt: str) -> None:
        self.robots_txt = robots_txt
        self._groups: dict[str, dict] = {}
        self._parse(robots_txt)

    def _parse(self, text: str) -> None:
        agents: list[str] = []
        current: dict | None = None
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()
            if key == "user-agent":
                agents.append(value.lower())
                current = None
                continue
            if key in ("disallow", "crawl-delay") and agents:
                for agent in agents:
                    group = self._groups.setdefault(
                        agent, {"disallow": [], "crawl_delay": 0.0}
                    )
                    current = group
                    if key == "disallow" and value:
                        group["disallow"].append(value)
                    elif key == "crawl-delay":
                        try:
                            group["crawl_delay"] = float(value)
                        except ValueError:
                            pass
        # comments/blank lines before any user-agent are ignored

    def _group_for(self, user_agent: str) -> dict | None:
        ua = user_agent.lower()
        if ua in self._groups:
            return self._groups[ua]
        token = ua.split("/", 1)[0]
        for agent, group in self._groups.items():
            if agent != "*" and agent in (ua, token):
                return group
        return self._groups.get("*")

    def delay_s(self, user_agent: str = "*") -> float:
        group = self._group_for(user_agent)
        return group["crawl_delay"] if group else 0.0

    def allowed(self, url: str, user_agent: str = "*") -> bool:
        group = self._group_for(user_agent)
        if not group:
            return True
        path = urlparse(url).path or "/"
        return not any(path == rule or path.startswith(rule) for rule in group["disallow"])


class Politeness:
    """Enforces a minimum interval between requests to the same host."""

    def __init__(self, robots_txt: str, user_agent: str = "merchantharvest") -> None:
        self.robots = RobotsRules(robots_txt)
        self.user_agent = user_agent
        self._last_hit: dict[str, float] = {}
        self._lock = threading.Lock()

    def delay_s(self, user_agent: str | None = None) -> float:
        return self.robots.delay_s(user_agent or self.user_agent)

    def allowed(self, url: str) -> bool:
        return self.robots.allowed(url, self.user_agent)

    def wait(self, host: str) -> None:
        """Block until the host may be hit again, then reserve the next slot."""
        delay = self.delay_s()
        with self._lock:
            now = time.monotonic()
            last = self._last_hit.get(host)
            if last is not None:
                remaining = last + delay - now
                if remaining > 0:
                    time.sleep(remaining)
            self._last_hit[host] = time.monotonic()
