"""Standard-library HTML parsers for the fixture catalog and detail pages."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urljoin


def _price_to_cents(value: str) -> int | None:
    text = value.strip().replace(",", "")
    if not text:
        return None
    if text.startswith("$"):
        text = text[1:]
    try:
        return int((Decimal(text) * 100).to_integral_value())
    except (InvalidOperation, ValueError):
        return None


def _int_cents(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        return None


class _CatalogParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict] = []
        self.next_url: str | None = None
        self._card_depth = 0
        self._card: dict | None = None
        self._capture: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = (attr.get("class") or "").split()
        if tag == "div" and "card" in classes:
            self._card = {"sku": attr.get("data-sku"), "title": None,
                          "price_cents": None, "detail_url": None}
            self._card_depth = 1
            return
        if self._card is not None:
            self._card_depth += 1
            if tag in ("span", "b") and ("nm" in classes or tag == "b"):
                self._capture = "title"
                self._buf = []
            elif tag == "i" and attr.get("data-price") is not None:
                # data-price is already expressed in whole cents.
                self._card["price_cents"] = _int_cents(attr.get("data-price"))
            elif tag == "span" and "price" in classes:
                self._capture = "price"
                self._buf = []
            elif tag == "a" and attr.get("href"):
                self._card["detail_url"] = attr["href"]
        elif tag == "a" and attr.get("rel") == "next" and attr.get("href"):
            self.next_url = attr["href"]

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        if self._capture in ("title", "price") and tag in ("span", "b"):
            text = "".join(self._buf).strip()
            if self._capture == "title":
                self._card["title"] = text
            else:
                self._card["price_cents"] = _price_to_cents(text)
            self._capture = None
            self._buf = []
        self._card_depth -= 1
        if self._card_depth == 0:
            if self._card.get("sku") and self._card.get("detail_url"):
                self.items.append(self._card)
            self._card = None


def parse_catalog(html: str, base: str) -> dict:
    """Return {"items": [{sku,title,price_cents,detail_url}], "next": url|None}."""
    parser = _CatalogParser()
    parser.feed(html)
    parser.close()
    items = []
    for item in parser.items:
        items.append({
            "sku": item["sku"],
            "title": item["title"],
            "price_cents": item["price_cents"],
            "detail_url": urljoin(base, item["detail_url"]),
        })
    next_url = urljoin(base, parser.next_url) if parser.next_url else None
    return {"items": items, "next": next_url}


class _CsrfParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.csrf: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        attr = dict(attrs)
        if attr.get("name") == "csrf" and self.csrf is None:
            self.csrf = attr.get("value")


def parse_login_csrf(html: str) -> str:
    parser = _CsrfParser()
    parser.feed(html)
    parser.close()
    if not parser.csrf:
        raise ValueError("csrf token not found in form")
    return parser.csrf


class _DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sku: str | None = None
        self.title: str | None = None
        self.price_cents: int | None = None
        self.stock: int | None = None
        self._capture: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        element_id = attr.get("id")
        classes = (attr.get("class") or "").split()
        if element_id == "title":
            self._capture = "title"
            self._buf = []
        elif "sku" in classes:
            self._capture = "sku"
            self._buf = []
        elif element_id == "price":
            # data-cents is already expressed in whole cents.
            self.price_cents = _int_cents(attr.get("data-cents"))
            self._capture = "price"
            self._buf = []
        elif element_id == "true-stock":
            self._capture = "stock"
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture is None:
            return
        text = "".join(self._buf).strip()
        if self._capture == "title":
            self.title = text
        elif self._capture == "sku":
            self.sku = text
        elif self._capture == "price" and self.price_cents is None:
            self.price_cents = _price_to_cents(text)
        elif self._capture == "stock":
            try:
                self.stock = int(text)
            except ValueError:
                self.stock = None
        self._capture = None
        self._buf = []


def parse_detail(html: str) -> dict:
    """Return {"sku","title","price_cents","stock"} from a detail page."""
    parser = _DetailParser()
    parser.feed(html)
    parser.close()
    missing = [name for name in ("sku", "title", "price_cents", "stock")
               if getattr(parser, name) is None]
    if missing:
        raise ValueError(f"detail page missing fields: {', '.join(missing)}")
    return {
        "sku": parser.sku,
        "title": parser.title,
        "price_cents": parser.price_cents,
        "stock": parser.stock,
    }


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr = dict(attrs)
        href = attr.get("href")
        if href:
            self.hrefs.append(href)


def parse_links(html: str, base: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(html)
    parser.close()
    return [urljoin(base, href) for href in parser.hrefs]
