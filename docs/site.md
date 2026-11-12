# Fixture site

`python -m merchantharvest.site` serves:

- `GET /` — home with a link to `/login` and `/catalog?page=1`
- `GET /login` — HTML form, hidden `csrf` token (changes each session)
- `POST /login` — needs `user`, `password`, `csrf`. Sets `session=` cookie. Credentials are in `fixtures/site/secrets.json` (local only).
- `GET /catalog?page=N` — messy HTML, 5 items per page, some cards wrap the title in `<span class="nm">`, some in `<b>`, prices sometimes in `data-price`, sometimes as text `$12.30`. A few links have tracking params `?utm_source=x&session=...`.
- `GET /item/{sku}` — detail page. Requires a valid session cookie or returns 401. ETag and Last-Modified are set; a matching `If-None-Match` / `If-Modified-Since` returns 304.
- `POST /item/{sku}/restock-alert` — RPA form (also CSRF) that must be submitted to reveal the hidden field `#true-stock` used as current stock. Without this POST, the detail page shows a placeholder stock of -1.
- `GET /robots.txt` — `Crawl-delay: 0` in production would be higher; the fixture uses `Crawl-delay: 0.05` so tests stay short. Honour it.
- Wave 2 changes prices/stock of some SKUs and adds a new SKU; some pages keep the same ETag (unchanged items).

429 is returned if a client exceeds 8 requests / 200ms from the same connection without a gap — a politeness tripwire. Stay under it by honouring crawl-delay.
