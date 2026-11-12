# merchantharvest

Incremental crawler + form RPA against a local fixture site (no internet required).

Already in the tree:

- `merchantharvest.site` — a deterministic local HTTP fixture (`python -m merchantharvest.site --port 8765 --wave 1`)
- `merchantharvest.http` — a tiny blocking HTTP/1.1 client that supports cookies
- `docs/` describing login/CSRF, pagination, ETags, and the target schema

Implemented:

- Politeness: robots.txt parsing (Disallow + Crawl-delay) with a per-host throttle (`merchantharvest.polite`)
- Checkpointable FIFO URL frontier that canonicalizes away `utm_*` / `session` params (`merchantharvest.frontier`)
- Login + CSRF form flow with the session cookie, plus the restock-alert RPA step that reveals real stock
- Standard-library listing/detail parsers handling both title/price markup variants (`merchantharvest.parse`)
- Conditional GET (`If-None-Match` / `If-Modified-Since`), sha256 content hashing and content/URL dedup
- Incremental runs emitting `upsert`, `new`, `price_change` and `stock_change` events (`merchantharvest.harvest`)
- `harvest` and `verify` CLI commands, with the harvest refusing any non-local host

```
# terminal A
python -m merchantharvest.site --port 8765 --wave 1 --data fixtures/site

# terminal B
python -m merchantharvest harvest --base http://127.0.0.1:8765 --out /tmp/mh-out --checkpoint /tmp/mh-out/cp.json

# then restart the site with --wave 2 and run harvest again with the same checkpoint
python -m merchantharvest.site --port 8765 --wave 2 --data fixtures/site
python -m merchantharvest harvest --base http://127.0.0.1:8765 --out /tmp/mh-out --checkpoint /tmp/mh-out/cp.json
```

The site is local. Do not crawl the public internet. Do not use Docker or a third-party crawler (Scrapy, Playwright, etc.).
