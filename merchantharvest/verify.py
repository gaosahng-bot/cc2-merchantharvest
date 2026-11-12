"""Verify a harvest output directory against an expected product image."""
from __future__ import annotations

import json
from pathlib import Path

COMPARE_FIELDS = ("title", "price_cents", "stock")
REQUIRED_PRODUCT_FIELDS = (
    "sku", "title", "price_cents", "currency", "stock", "canonical_url", "content_hash",
)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify(out_dir: str, expect: str) -> tuple[bool, str]:
    out = Path(out_dir)
    products_path = out / "products.jsonl"
    events_path = out / "events.jsonl"
    report_path = out / "crawl_report.json"
    failures: list[str] = []

    for path in (products_path, events_path, report_path):
        if not path.exists():
            failures.append(f"missing output file: {path}")
    if failures:
        return False, "; ".join(failures)

    expected = json.loads(Path(expect).read_text(encoding="utf-8"))
    expected_products = expected["products"]
    products = {row["sku"]: row for row in _read_jsonl(products_path)}
    events = _read_jsonl(events_path)

    if set(products) != set(expected_products):
        missing = sorted(set(expected_products) - set(products))
        extra = sorted(set(products) - set(expected_products))
        failures.append(f"sku set mismatch (missing={missing}, extra={extra})")

    for sku, want in expected_products.items():
        got = products.get(sku)
        if got is None:
            continue
        for field in COMPARE_FIELDS:
            if got.get(field) != want.get(field):
                failures.append(
                    f"{sku}.{field}: expected {want.get(field)!r}, got {got.get(field)!r}"
                )
        for field in REQUIRED_PRODUCT_FIELDS:
            if field not in got or got[field] in (None, ""):
                failures.append(f"{sku}: missing/empty field {field}")
        if "?" in got.get("canonical_url", ""):
            query = got["canonical_url"].split("?", 1)[1]
            for key in query.split("&"):
                name = key.split("=", 1)[0]
                if name.startswith("utm_") or name == "session":
                    failures.append(f"{sku}: volatile query param {name!r} left in canonical_url")
        if got.get("stock") == -1:
            failures.append(f"{sku}: stock still hidden (-1), restock RPA did not run")

    events_by_sku: dict[str, set[str]] = {}
    for event in events:
        events_by_sku.setdefault(event.get("sku", ""), set()).add(event.get("type", ""))

    # Infer the SKUs that must show change events from the expected image itself
    # by comparing against the previous wave when available, otherwise fall back
    # to requiring new/upsert coverage for every SKU.
    required: dict[str, set[str]] = {}
    prev_path = Path(expect).with_name(
        f"wave{int(expected.get('wave', 1)) - 1}.json"
    )
    if prev_path.exists():
        prev = json.loads(prev_path.read_text(encoding="utf-8"))["products"]
        for sku, want in expected_products.items():
            old = prev.get(sku)
            if old is None:
                required[sku] = {"new"}
                continue
            need: set[str] = set()
            if old.get("price_cents") != want.get("price_cents"):
                need.add("price_change")
            if old.get("stock") != want.get("stock"):
                need.add("stock_change")
            if need:
                required[sku] = need
    else:
        required = {sku: {"upsert"} for sku in expected_products}

    for sku, need in required.items():
        seen = events_by_sku.get(sku, set())
        missing_types = sorted(need - seen)
        if missing_types:
            failures.append(f"{sku}: missing expected event types {missing_types}")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    for key in ("pages_fetched", "pages_not_modified", "pages_deduped",
                "items", "events", "robots_delay_s", "errors"):
        if key not in report:
            failures.append(f"crawl_report.json missing key {key}")
    if report.get("items") != len(expected_products):
        failures.append(
            f"report items={report.get('items')} but expected {len(expected_products)}"
        )
    if report.get("errors"):
        failures.append(f"crawl reported errors: {report['errors']}")

    if failures:
        return False, f"FAIL ({len(failures)} problem(s)):\n- " + "\n- ".join(failures)
    return True, (
        f"OK: {len(products)} products match {Path(expect).name}; "
        f"{len(events)} events cover {len(required)} changed/new sku(s)"
    )
