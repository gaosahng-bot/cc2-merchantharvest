# Output schema

`--out` directory after both waves (or after wave 1, then wave 2 incremental):

- `products.jsonl` — current product image, one object per sku:
  `{"sku","title","price_cents","currency","stock","canonical_url","content_hash"}`
- `events.jsonl` — append-only change log:
  `{"ts","sku","type":"upsert"|"price_change"|"stock_change"|"new","old":...,"new":...}`
- `crawl_report.json` — `{pages_fetched, pages_not_modified, pages_deduped, items, events, robots_delay_s, errors}`

Canonical URL must drop `utm_*` and `session` query parameters.
`content_hash` is sha256 of the canonical detail HTML body (the 200 body, not a 304).

Expected images for the two waves live in `fixtures/expected/wave1.json` and `wave2.json`.
`python -m merchantharvest verify --out DIR --expect fixtures/expected/wave2.json` should exist and compare
current products (by sku) plus the set of event types per sku.
