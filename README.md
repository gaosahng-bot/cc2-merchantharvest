# merchantharvest

Incremental crawler + form RPA against a local fixture site (no internet required).

Already in the tree:

- `merchantharvest.site` — a deterministic local HTTP fixture (`python -m merchantharvest.site --port 8765 --wave 1`)
- `merchantharvest.http` — a tiny blocking HTTP/1.1 client that supports cookies
- `docs/` describing login/CSRF, pagination, ETags, and the target schema

Not implemented:

- Politeness / crawl-delay / per-host concurrency (`merchantharvest.polite`)
- URL frontier with checkpoint (`merchantharvest.frontier`)
- Conditional GET + content-hash dedup that ignores volatile query params
- Login + CSRF form flow
- Listing/detail parsers into the normalized schema
- Incremental second wave that emits price/stock change events
- The harvest CLI

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
