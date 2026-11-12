"""Local fixture HTTP site. Complete."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import threading

WAVE_LOCK = threading.Lock()


def load_catalog(data_dir: Path, wave: int) -> dict:
    base = json.loads((data_dir / "catalog.json").read_text())
    if wave >= 2:
        delta = json.loads((data_dir / "wave2_delta.json").read_text())
        by = {p["sku"]: p for p in base["products"]}
        for sku, ch in delta.get("changes", {}).items():
            by[sku] = {**by[sku], **ch}
        for p in delta.get("added", []):
            by[p["sku"]] = p
        base["products"] = list(by.values())
    return base


def etag_for(payload: str) -> str:
    return '"' + hashlib.sha1(payload.encode()).hexdigest()[:16] + '"'


class Handler(BaseHTTPRequestHandler):
    server_version = "MerchHarvestSite/0.1"

    def log_message(self, fmt, *args):  # quieter
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    def _catalog(self):
        return load_catalog(self.server.data_dir, self.server.wave)

    def _send(self, code, body: bytes, headers: dict | None = None):
        self.send_response(code)
        headers = dict(headers or {})
        headers.setdefault("Content-Type", "text/html; charset=utf-8")
        headers.setdefault("Content-Length", str(len(body)))
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _cookies(self) -> dict:
        raw = self.headers.get("Cookie") or ""
        out = {}
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
        return out

    def _authed(self) -> bool:
        return self._cookies().get("session") == self.server.session_value

    def do_GET(self):
        self.server.hits += 1
        u = urlparse(self.path)
        if u.path == "/robots.txt":
            body = "User-agent: *\nCrawl-delay: 0.05\nDisallow: /login\n"
            return self._send(200, body.encode(), {"Content-Type": "text/plain"})
        if u.path == "/":
            html = "<html><body><a href='/login'>login</a> <a href='/catalog?page=1'>catalog</a></body></html>"
            return self._send(200, html.encode())
        if u.path == "/login":
            tok = self.server.csrf
            html = (
                "<html><body><form method='post' action='/login'>"
                "<input name='user'/><input name='password' type='password'/>"
                f"<input type='hidden' name='csrf' value='{tok}'/>"
                "<button type='submit'>go</button></form></body></html>"
            )
            return self._send(200, html.encode())
        if u.path == "/catalog":
            qs = parse_qs(u.query)
            page = int(qs.get("page", ["1"])[0])
            products = self._catalog()["products"]
            per = 5
            start = (page - 1) * per
            chunk = products[start:start + per]
            cards = []
            for i, p in enumerate(chunk):
                track = f"?utm_source=home&session=junk{i}"
                if i % 2 == 0:
                    title = f"<span class='nm'>{p['title']}</span>"
                    price = f"<i data-price='{p['price_cents']}'></i>"
                else:
                    title = f"<b>{p['title']}</b>"
                    dollars = p["price_cents"] / 100.0
                    price = f"<span class='price'>${dollars:.2f}</span>"
                cards.append(
                    f"<div class='card' data-sku='{p['sku']}'>{title}{price}"
                    f"<a href='/item/{p['sku']}{track}'>view</a></div>"
                )
            prev_next = ""
            if start + per < len(products):
                prev_next += f"<a rel='next' href='/catalog?page={page+1}'>next</a>"
            html = "<html><body>" + "".join(cards) + prev_next + "</body></html>"
            return self._send(200, html.encode())
        if u.path.startswith("/item/"):
            if not self._authed():
                return self._send(401, b"auth required")
            sku = u.path.split("/item/", 1)[1].split("/")[0]
            products = {p["sku"]: p for p in self._catalog()["products"]}
            if sku not in products:
                return self._send(404, b"missing")
            p = products[sku]
            # stock hidden unless restock form posted in this session
            shown_stock = p["stock"] if sku in self.server.revealed else -1
            html = (
                f"<html><body><h1 id='title'>{p['title']}</h1>"
                f"<p class='sku'>{sku}</p>"
                f"<p id='price' data-cents='{p['price_cents']}'>{p['price_cents']}</p>"
                f"<p id='true-stock'>{shown_stock}</p>"
                f"<form method='post' action='/item/{sku}/restock-alert'>"
                f"<input type='hidden' name='csrf' value='{self.server.csrf}'/>"
                "<button>reveal</button></form></body></html>"
            )
            # ETag identifies product content (including real stock). The wave
            # id and reveal/rendering state must not change it, so an unchanged
            # product keeps the same ETag across waves and answers 304 to
            # conditional requests even after the restock-alert RPA step, while
            # a price or stock change produces a new ETag and a fresh 200.
            tag = etag_for(
                f"{p['sku']}|{p['title']}|{p['price_cents']}|{p['stock']}"
            )
            lm = self.server.last_modified
            inm = self.headers.get("If-None-Match")
            ims = self.headers.get("If-Modified-Since")
            # RFC 9110: when both validators are supplied both must match;
            # a fixed Last-Modified across waves must not mask ETag changes.
            if (inm == tag and (not ims or ims == lm)) or (not inm and ims == lm):
                return self._send(304, b"", {"ETag": tag, "Last-Modified": lm})
            return self._send(200, html.encode(), {"ETag": tag, "Last-Modified": lm})
        return self._send(404, b"no")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        form = parse_qs(raw.decode(), keep_blank_values=True)
        flat = {k: v[0] if v else "" for k, v in form.items()}
        u = urlparse(self.path)
        if u.path == "/login":
            secrets = json.loads((self.server.data_dir / "secrets.json").read_text())
            if flat.get("csrf") != self.server.csrf:
                return self._send(400, b"bad csrf")
            if flat.get("user") == secrets["user"] and flat.get("password") == secrets["password"]:
                body = b"ok <a href='/catalog?page=1'>catalog</a>"
                # Set-Cookie
                self.send_response(302)
                self.send_header("Location", "/catalog?page=1")
                self.send_header("Set-Cookie", f"session={self.server.session_value}; Path=/")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            return self._send(401, b"bad login")
        if u.path.startswith("/item/") and u.path.endswith("/restock-alert"):
            if not self._authed():
                return self._send(401, b"auth required")
            if flat.get("csrf") != self.server.csrf:
                return self._send(400, b"bad csrf")
            sku = u.path.split("/item/", 1)[1].split("/")[0]
            self.server.revealed.add(sku)
            return self._send(200, b"revealed")
        return self._send(404, b"no")


def serve(data_dir: Path, port: int, wave: int, verbose: bool = False):
    secrets_ok = (data_dir / "secrets.json").exists()
    if not secrets_ok:
        raise SystemExit("missing fixtures")
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.data_dir = data_dir
    httpd.wave = wave
    httpd.verbose = verbose
    httpd.hits = 0
    httpd.csrf = "csrf-" + hashlib.sha1(f"wave{wave}".encode()).hexdigest()[:10]
    httpd.session_value = "sess-" + hashlib.sha1(f"wave{wave}-session".encode()).hexdigest()[:12]
    httpd.revealed = set()
    httpd.last_modified = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    print(f"merchantharvest site wave={wave} on http://127.0.0.1:{port}")
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--wave", type=int, default=1)
    p.add_argument("--data", default="fixtures/site")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)
    serve(Path(args.data), args.port, args.wave, args.verbose)


if __name__ == "__main__":
    main()
