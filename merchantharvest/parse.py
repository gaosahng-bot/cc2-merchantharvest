"""HTML parsers for catalog and detail pages — NOT implemented yet."""
from __future__ import annotations


def parse_catalog(html: str, base: str) -> list[dict]:
    """Return [{"sku","title","price_cents","detail_url"}] from a catalog page, plus a next-page URL or None.

    Actually return {"items": [...], "next": url|None}.
    """
    raise NotImplementedError


def parse_login_csrf(html: str) -> str:
    raise NotImplementedError


def parse_detail(html: str) -> dict:
    """Return {"sku","title","price_cents","stock"} from a detail page."""
    raise NotImplementedError
