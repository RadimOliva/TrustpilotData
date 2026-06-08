# Trustpilot Scraping Research — Internet & Software (US) Category

_Research date: 2026-06-05_

---

## 1. Target URL

The Internet & Software category for the US is accessible at:

```
https://www.trustpilot.com/categories/internet_software_telecommunications?country=US&page=1
```

Other potential URL variants to test:
- `https://www.trustpilot.com/categories/electronics_technology?country=US`
- Filter params: `?numberofreviews=0&status=all&country=US&page=N`

---

## 2. Scale & Pagination

| Parameter | Value |
|---|---|
| Companies per page | 20 (standard listing) |
| Maximum pages | 500 |
| Maximum reachable companies | **10,000** (20 × 500) |
| Stated total in category | ~10,000 (matches the cap) |

> The site reportedly lists 10,000 companies in this category, which coincides exactly with the pagination ceiling. In practice, dynamic reordering between pages can cause some duplicates and missed entries when naively iterating by URL page number (see Section 6).

---

## 3. Available Data Fields

### From category listing pages (via `__NEXT_DATA__` JSON)
These fields are present directly on category/search result pages without visiting individual company profiles:

| Field | Notes |
|---|---|
| `businessUnitId` | Trustpilot internal ID |
| `displayName` | Company name |
| `trustScore` | Numeric score (e.g., 4.2) |
| `stars` | Star rating bucket (1–5) |
| `numberOfReviews` | Total review count |
| `logoUrl` | Company logo URL |
| `profileUrl` / slug | Path to full company page |
| `location` | Country/city if available |
| `categories` | Array of category IDs and display names |
| `websiteUrl` | Company website (sometimes present) |

### From individual company profile pages (second pass required)
Requires fetching each company's profile URL separately:

| Field | Notes |
|---|---|
| `description` / "About" | Free-text company description (main target for item d) |
| `contact` | Email, phone, address |
| `verificationStatus` | Whether the company is claimed/verified |
| Individual reviews | Full review text, dates, replies |

---

## 4. Getting Item (d) — Short Company Description

This is the trickiest field. Trustpilot does **not** expose a "short description" on category listing pages. Here are the viable approaches, ranked by effort vs. quality:

### Option A — Profile page "About" section (recommended, two-pass)
Each company profile page (e.g., `trustpilot.com/review/example.com`) contains an "About" text block in its `__NEXT_DATA__` JSON under a path like:
```
pageProps.businessUnit.description
```
**Trade-off:** Requires a second HTTP request per company. For 10,000 companies this is 10,000 additional requests — feasible but requires rate limiting (see Section 6).

### Option B — Company website meta description (third-pass)
If the company's website URL is present in the listing or profile data, fetch the homepage and extract the `<meta name="description">` tag. This often gives a clean, marketing-facing one-liner.
**Trade-off:** Adds a third request tier and varies widely in quality.

### Option C — Trustpilot category tags as a proxy
Each company is assigned to one or more Trustpilot subcategories (e.g., "SaaS", "Web Hosting", "Email Marketing"). These subcategory labels can serve as a coarse descriptor when a free-text description is unavailable or empty.
**Trade-off:** Not a description — more of a label. But it's free from the listing data.

### Option D — LLM-generated description (post-processing)
After collecting company name + categories, use an LLM (e.g., Claude API) to produce a one-sentence description. Useful as a fallback when the "About" field is empty, which is common for unclaimed profiles.
**Trade-off:** Inference cost; accuracy depends on whether the company is well-known.

### Practical recommendation
Run a **two-pass scrape**: pass 1 collects all listing data (fields in Section 3, first table) for all 10,000 companies; pass 2 fetches individual profile pages only for companies where a description is needed. Use Option C (category tags) as an immediate fallback and Option D (LLM) for any remaining blanks.

---

## 5. Technical Approach — How to Extract the Data

### Method: Parse `__NEXT_DATA__` JSON (no HTML parsing needed)

Trustpilot is built on Next.js. Every page embeds a `<script id="__NEXT_DATA__" type="application/json">` tag in the HTML that contains all page data as structured JSON — the same data that gets rendered into the visible HTML.

**Steps:**
1. Make a standard HTTP GET request to a category page URL.
2. Parse the HTML to find `<script id="__NEXT_DATA__">`.
3. `json.loads()` the tag contents.
4. Navigate: `data["props"]["pageProps"]["businessUnits"]["businesses"]` (exact path may vary — verify with browser DevTools on the live page).

### Alternative method: Internal Next.js JSON API
Trustpilot exposes a Next.js data endpoint that returns pure JSON without HTML:
```
https://www.trustpilot.com/_next/data/{BUILD_ID}/categories/{categoryId}.json?page=N&country=US
```
The `BUILD_ID` changes with site deploys and must be extracted from any page's `__NEXT_DATA__` → `buildId` field before use. This endpoint returns the same data as the `__NEXT_DATA__` approach but without HTML parsing overhead.

---

## 6. Anti-Bot Protections & Rate Limiting

| Protection | Detail |
|---|---|
| WAF | Cloudflare (enterprise-tier) |
| JavaScript challenges | Yes — but `__NEXT_DATA__` is present in the raw HTML response (no JS execution needed for data extraction) |
| IP-based rate limiting | Yes — requests blocked after sustained high volume from a single IP |
| CAPTCHA | Triggered under high-speed or pattern-detected scraping |
| DC IP blocking | Datacenter IPs commonly flagged; residential proxies recommended for scale |

### Mitigations
- **Delays:** 1–3 seconds between requests is the standard safe interval.
- **Proxies:** Residential or mobile proxy rotation for large-scale runs.
- **Headers:** Mimic browser headers (`User-Agent`, `Accept-Language`, `Referer`).
- **No JS required:** Since data is in `__NEXT_DATA__`, you do not need Playwright/Selenium for category listing pages — plain `requests` + `BeautifulSoup`/`lxml` or `httpx` is sufficient.
- **Pagination stability:** Page-number shifting (companies moving between pages between requests) can cause duplicates/gaps. Mitigate by collecting seen `businessUnitId` values and deduplicating.

---

## 7. Realistic Yield Estimate

| Scenario | Setup | Estimated Yield | Time Estimate |
|---|---|---|---|
| Conservative (no proxies, 2s delay) | `requests` + headers | 3,000–6,000 companies | 2–4 hours |
| Moderate (proxy rotation, 1s delay) | `httpx` + proxy pool | 8,000–10,000 companies | 3–5 hours |
| Aggressive (proxy pool, fast) | Playwright or ScraperAPI | ~10,000 companies | 1–2 hours |
| With description (two-pass) | Any of the above × 2 | ~10,000 with descriptions | 2× above |

---

## 8. Third-Party Scraping Services (if DIY is too complex)

| Service | Notes |
|---|---|
| **Apify** | Multiple ready-made Trustpilot actors; pay-per-use; handles proxies and anti-bot |
| **ScraperAPI** | Proxy + JS rendering API; good for `requests`-based scrapers |
| **Scrapfly** | Published open-source Trustpilot scraper on GitHub (`scrapfly/scrapfly-scrapers`); well-maintained |
| **Outscraper** | Commercial Trustpilot scraper with API; no-code option |
| **Browse AI** | No-code robot approach; slower but accessible |

Scrapfly's open-source repo is the best starting point for custom Python code:
`https://github.com/scrapfly/scrapfly-scrapers/tree/main/trustpilot-scraper`

---

## 9. Official Trustpilot API

Trustpilot has a developer API (`developers.trustpilot.com`) with:
- **Business Units API** — get TrustScore, star rating, category, review count for a specific domain
- **Categories API** — list business units in a category

**Limitation:** The API requires registration and an API key. It is gated (primarily for businesses on Trustpilot's paid plans) and not freely available for bulk category crawling. It is not a practical path to getting 10,000 companies without a commercial agreement.

---

## 10. Legal & Ethical Considerations

- `robots.txt` is **not legally binding** but signals intent; ignoring it increases regulatory risk (especially under EU/CNIL rules). Always check `trustpilot.com/robots.txt` before running.
- Trustpilot's ToS prohibit automated scraping. However, scraping **publicly available, non-personal** data (company names, aggregate scores) for research/internal analysis is generally low legal risk under US law (see *hiQ v. LinkedIn* precedent).
- Review counts and trust scores are **aggregate data**, not personal data — lower GDPR/CCPA exposure than scraping reviewer names or text.
- **Best practices:** Use delays, do not store or republish raw review text, and do not log in to bypass any access controls.

---

## 11. Recommended Implementation Stack

```
Language:   Python 3.11+
HTTP:       httpx (async) or requests
Parsing:    Built-in json module (no HTML parsing needed for __NEXT_DATA__)
Storage:    SQLite (via sqlite3) for deduplication; export to CSV/JSON
Rate ctrl:  asyncio.sleep() with jitter; semaphore to cap concurrency
Proxies:    ScraperAPI or Brightdata residential (optional for small runs)
```

---

## 12. Suggested Scraping Workflow

```
1. GET https://www.trustpilot.com/categories/internet_software_telecommunications?country=US&page=1
2. Extract __NEXT_DATA__ → parse buildId + businesses list
3. Store all company records (name, score, review count, slug, categories)
4. Increment page; repeat until page returns empty businesses or hits page 500
5. Deduplicate by businessUnitId
6. (Optional) For each company slug, GET https://www.trustpilot.com/review/{slug}
   → extract description from __NEXT_DATA__ → pageProps.businessUnit.description
7. Export to CSV / SQLite
```

---

## Sources

- [How to Scrape Trustpilot in 2026 | Scraperly](https://scraperly.com/scrape/trustpilot)
- [How to Scrape Trustpilot.com Reviews and Company Data | Scrapfly Blog](https://scrapfly.io/blog/posts/how-to-scrape-trustpilot-com-reviews)
- [Trustpilot Scraper | Apify (casper11515)](https://apify.com/casper11515/trustpilot-reviews-scraper)
- [How to Scrape Trustpilot Company data | WebScraper.io](https://webscraper.io/blog/how-to-scrape-trustpilot-company-listings)
- [How to Scrape Trustpilot Reviews and Company Data | ScraperAPI Blog](https://www.scraperapi.com/blog/scraping-trustpilot-reviews/)
- [How to Scrape Trustpilot Reviews and Company Data in 5 Steps | RoundProxies](https://roundproxies.com/blog/trustpilot-scraper/)
- [scrapfly/scrapfly-scrapers — trustpilot-scraper | GitHub](https://github.com/scrapfly/scrapfly-scrapers/tree/main/trustpilot-scraper)
- [Business Units API | Trustpilot Developers](https://developers.trustpilot.com/business-units-api)
- [Categories API | Trustpilot Developers](https://developers.trustpilot.com/categories-api/)
- [Is Web Scraping Legal in 2026? | Browserless](https://www.browserless.io/blog/is-web-scraping-legal)
- [DataForSEO — Trustpilot Business Data API](https://docs.dataforseo.com/v3/business_data-trustpilot-overview/)
