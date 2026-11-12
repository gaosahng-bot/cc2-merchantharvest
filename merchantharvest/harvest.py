"""Incremental harvest: polite crawl, login/RPA, conditional GET, dedup, events."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from merchantharvest.frontier import Frontier, canonicalize_url
from merchantharvest.http import Client
from merchantharvest.parse import (
    parse_catalog,
    parse_detail,
    parse_links,
    parse_login_csrf,
)
from merchantharvest.polite import Politeness

CURRENCY = "USD"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write_json(path: Path, payload) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def _load_checkpoint(path: Path) -> dict:
    if not path.exists():
        return {"run_count": 0, "validators": {}, "products": {}, "frontier": None}
    return json.loads(path.read_text())


class HarvestRunner:
    def __init__(self, base: str, out_dir: Path, checkpoint_path: Path) -> None:
        self.base = base.rstrip("/")
        parsed_base = urlparse(self.base)
        if parsed_base.scheme != "http" or parsed_base.hostname not in LOCAL_HOSTS:
            raise ValueError(
                f"refusing to crawl {self.base!r}: only the local fixture host is allowed"
            )
        self.host = parsed_base.netloc
        self.out_dir = out_dir
        self.checkpoint_path = checkpoint_path
        self.client = Client()
        self.errors: list[str] = []
        self.pages_fetched = 0
        self.pages_not_modified = 0
        self.pages_deduped = 0
        self.events_emitted = 0

        state = _load_checkpoint(checkpoint_path)
        self.run_count = int(state.get("run_count", 0)) + 1
        self.validators: dict[str, dict] = state.get("validators", {})
        self.products: dict[str, dict] = state.get("products", {})
        self.frontier = Frontier(self.base)
        saved_frontier = state.get("frontier")
        # Resume only a run that died mid-crawl; a finished run starts a fresh
        # frontier so wave 2 can discover new pages again.
        if saved_frontier and saved_frontier.get("queue"):
            self.frontier.load(saved_frontier)

    def _save_checkpoint(self) -> None:
        payload = {
            "run_count": self.run_count,
            "validators": self.validators,
            "products": self.products,
            "frontier": self.frontier.dump(),
        }
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.checkpoint_path, payload)

    def _request(self, method: str, url: str, **kwargs):
        self.polite.wait(self.host)
        return self.client.request(method, url, **kwargs)

    def _push(self, url: str) -> None:
        if not self.polite.allowed(url):
            return
        if not self.frontier.push(url):
            self.pages_deduped += 1

    def _emit(self, event: dict) -> None:
        event = {"ts": _now_iso(), **event}
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
        self.events_emitted += 1

    def _load_robots(self) -> None:
        robots_url = self.base + "/robots.txt"
        resp = self.client.request("GET", robots_url)
        if resp.status != 200:
            raise RuntimeError(f"robots.txt unavailable: HTTP {resp.status}")
        self.polite = Politeness(resp.text)
        self.robots_delay = self.polite.delay_s()

    def _login(self) -> None:
        login_url = self.base + "/login"
        resp = self._request("GET", login_url)
        if resp.status != 200:
            raise RuntimeError(f"login page failed: HTTP {resp.status}")
        csrf = parse_login_csrf(resp.text)
        secrets_path = Path(__file__).resolve().parent.parent / "fixtures" / "site" / "secrets.json"
        if not secrets_path.exists():
            secrets_path = Path("fixtures/site/secrets.json")
        secrets = json.loads(secrets_path.read_text())
        resp = self._request(
            "POST", login_url,
            form={"user": secrets["user"], "password": secrets["password"], "csrf": csrf},
        )
        if resp.status not in (200, 302) or "session" not in self.client.cookies:
            raise RuntimeError(f"login failed: HTTP {resp.status}")

    def _handle_home(self, url: str, resp) -> None:
        for href in parse_links(resp.text, url):
            self._push(href)

    def _handle_catalog(self, url: str, resp) -> None:
        parsed = parse_catalog(resp.text, url)
        for item in parsed["items"]:
            self._push(item["detail_url"])
        if parsed["next"]:
            self._push(parsed["next"])

    def _handle_detail(self, url: str) -> None:
        canonical = canonicalize_url(url)
        headers = {}
        stored = self.validators.get(canonical)
        if stored:
            if stored.get("etag"):
                headers["If-None-Match"] = stored["etag"]
            if stored.get("last_modified"):
                headers["If-Modified-Since"] = stored["last_modified"]
        resp = self._request("GET", url, headers=headers)
        if resp.status == 304:
            self.pages_not_modified += 1
            return
        if resp.status != 200:
            self.errors.append(f"{canonical}: HTTP {resp.status}")
            return
        self.pages_fetched += 1

        # RPA: submit the restock-alert form, then re-fetch to reveal true stock.
        csrf = parse_login_csrf(resp.text)
        alert_url = f"{self.base}/item/{urlparse(canonical).path.rsplit('/', 1)[-1]}/restock-alert"
        alert = self._request("POST", alert_url, form={"csrf": csrf})
        if alert.status != 200:
            self.errors.append(f"{alert_url}: HTTP {alert.status}")
            return
        # Fresh GET without conditional headers: the revealed body is a new revision.
        resp = self._request("GET", url)
        if resp.status != 200:
            self.errors.append(f"{canonical} after restock: HTTP {resp.status}")
            return
        self.pages_fetched += 1

        content_hash = hashlib.sha256(resp.body).hexdigest()
        if any(p.get("content_hash") == content_hash
               for sku, p in self.products.items()
               if p.get("canonical_url") != canonical):
            self.pages_deduped += 1
            return

        detail = parse_detail(resp.text)
        sku = detail["sku"]
        current = {
            "sku": sku,
            "title": detail["title"],
            "price_cents": detail["price_cents"],
            "currency": CURRENCY,
            "stock": detail["stock"],
            "canonical_url": canonical,
            "content_hash": content_hash,
        }
        self.validators[canonical] = {
            "etag": resp.header("ETag"),
            "last_modified": resp.header("Last-Modified"),
        }

        previous = self.products.get(sku)
        if previous is None:
            self._emit({"sku": sku, "type": "upsert", "old": None, "new": current})
            if self.run_count > 1:
                self._emit({"sku": sku, "type": "new", "old": None, "new": current})
        else:
            if previous["price_cents"] != current["price_cents"]:
                self._emit({"sku": sku, "type": "price_change",
                            "old": previous["price_cents"], "new": current["price_cents"]})
            if previous["stock"] != current["stock"]:
                self._emit({"sku": sku, "type": "stock_change",
                            "old": previous["stock"], "new": current["stock"]})
        self.products[sku] = current

    def _write_outputs(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        products_path = self.out_dir / "products.jsonl"
        with products_path.open("w", encoding="utf-8") as fh:
            for sku in sorted(self.products):
                fh.write(json.dumps(self.products[sku], sort_keys=True) + "\n")
        report = {
            "pages_fetched": self.pages_fetched,
            "pages_not_modified": self.pages_not_modified,
            "pages_deduped": self.pages_deduped,
            "items": len(self.products),
            "events": self.events_emitted,
            "robots_delay_s": self.robots_delay,
            "errors": self.errors,
        }
        _atomic_write_json(self.out_dir / "crawl_report.json", report)

    def run(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.out_dir / "events.jsonl"
        self._load_robots()
        self._login()
        self.frontier.push(self.base + "/")

        while True:
            url = self.frontier.pop()
            if url is None:
                break
            path = urlparse(url).path
            try:
                if path == "/":
                    resp = self._request("GET", url)
                    self.pages_fetched += 1
                    self._handle_home(url, resp)
                elif path.startswith("/catalog"):
                    resp = self._request("GET", url)
                    self.pages_fetched += 1
                    self._handle_catalog(url, resp)
                elif path.startswith("/item/"):
                    self._handle_detail(url)
                else:
                    self.errors.append(f"{url}: unknown path, skipped")
            except Exception as exc:  # keep crawling; surface the failure in the report
                self.errors.append(f"{url}: {type(exc).__name__}: {exc}")
            self._save_checkpoint()

        self._write_outputs()
        self._save_checkpoint()


def harvest(base: str, out_dir: str, checkpoint: str) -> None:
    out_path = Path(out_dir)
    checkpoint_path = Path(checkpoint)
    runner = HarvestRunner(base, out_path, checkpoint_path)
    runner.run()
