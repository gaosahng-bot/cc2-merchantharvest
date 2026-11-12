"""Tiny blocking HTTP/1.1 client with cookie jar. Complete. HTTP only (no TLS)."""
from __future__ import annotations

import http.client
from urllib.parse import urlparse, urljoin
from http.cookies import SimpleCookie


class Client:
    def __init__(self) -> None:
        self.cookies: dict[str, str] = {}

    def request(self, method: str, url: str, body: bytes | None = None, headers: dict | None = None, form: dict | None = None) -> "Response":
        u = urlparse(url)
        assert u.scheme == "http", "fixture client is HTTP-only"
        host = u.hostname or "127.0.0.1"
        port = u.port or 80
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        hdrs = {"Host": f"{host}:{port}", "Connection": "close", "User-Agent": "merchantharvest/0.1"}
        if self.cookies:
            hdrs["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        data = body
        if form is not None:
            from urllib.parse import urlencode
            data = urlencode(form).encode()
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        if data is not None:
            hdrs["Content-Length"] = str(len(data))
        if headers:
            hdrs.update(headers)
        conn = http.client.HTTPConnection(host, port, timeout=10)
        try:
            conn.request(method, path, body=data, headers=hdrs)
            r = conn.getresponse()
            raw = r.read()
            resp = Response(r.status, dict(r.getheaders()), raw, url)
        finally:
            conn.close()
        # cookies
        set_cookie = resp.headers.get("Set-Cookie") or resp.headers.get("set-cookie")
        # HTTPConnection folds headers; getheaders may have multiple
        for k, v in resp.headers.items():
            if k.lower() == "set-cookie":
                c = SimpleCookie()
                c.load(v)
                for name, morsel in c.items():
                    self.cookies[name] = morsel.value
        return resp


class Response:
    def __init__(self, status: int, headers: dict, body: bytes, url: str) -> None:
        self.status = status
        self.headers = {k: v for k, v in headers.items()}
        # also expose case-insensitive access
        self._hlower = {k.lower(): v for k, v in headers.items()}
        self.body = body
        self.url = url

    def header(self, name: str) -> str | None:
        return self._hlower.get(name.lower())

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")
