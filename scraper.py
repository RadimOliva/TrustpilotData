#!/usr/bin/env python3
"""
Trustpilot category scraper — Internet & Software (US)
Single-pass, rate-limited, checkpoint-resumable. Outputs CSV.
Requires: pip install playwright && playwright install chromium
"""

import csv
import json
import os
import random
import time
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── Configuration ──────────────────────────────────────────────────────────────

CATEGORY_SLUG  = "internet_software"
COUNTRY        = "US"
MAX_PAGES      = 500
DELAY_MIN      = 2.0   # seconds between page navigations (lower bound)
DELAY_MAX      = 4.0   # seconds between page navigations (upper bound)
PAGE_TIMEOUT   = 30000 # ms — navigation timeout per page
EMPTY_STOP     = 3     # stop after this many consecutive empty/failed pages
HEADLESS       = True  # set False to watch the browser (also helps if blocked)

OUTPUT_CSV      = "trustpilot_internet_software_us.csv"
CHECKPOINT_FILE = ".scrape_checkpoint.json"

BASE_URL = (
    "https://www.trustpilot.com/categories/{slug}"
    "?country={country}&page={page}"
)

CSV_FIELDS = [
    "businessUnitId",
    "displayName",
    "identifyingName",
    "profileUrl",
    "trustScore",
    "stars",
    "numberOfReviews",
    "isRecommendedInCategories",
    "location_address",
    "location_city",
    "location_zipCode",
    "location_country",
    "contact_website",
    "contact_email",
    "contact_phone",
    "categories",
    "logoUrl",
]

# ── Page data extraction ───────────────────────────────────────────────────────

def get_next_data(page, url):
    """Navigate to url and return the parsed __NEXT_DATA__ dict, or None."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
    except PlaywrightTimeout:
        print("  [timeout on navigation]", flush=True)
        return None

    try:
        content = page.evaluate(
            "() => document.getElementById('__NEXT_DATA__')?.textContent ?? null"
        )
    except Exception as exc:
        print(f"  [evaluate error] {exc}", flush=True)
        return None

    if not content:
        # Page may be a Cloudflare challenge — show current URL for diagnosis
        current = page.url
        print(f"  [no __NEXT_DATA__] landed on: {current}", flush=True)
        return None

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        print(f"  [JSON parse error] {exc}", flush=True)
        return None


# ── Business list extraction ───────────────────────────────────────────────────

# Multiple path candidates because the exact location in __NEXT_DATA__ can
# shift between Trustpilot's Next.js deployments.
_BUSINESS_PATHS = [
    lambda d: d["props"]["pageProps"]["businessUnits"]["businesses"],
    lambda d: d["props"]["pageProps"]["businesses"],
    lambda d: d["props"]["pageProps"]["categoryBusinessUnits"]["businesses"],
    lambda d: d["props"]["pageProps"]["categoriesData"]["businesses"],
]


def parse_businesses(next_data):
    for fn in _BUSINESS_PATHS:
        try:
            result = fn(next_data)
            if isinstance(result, list):
                return result
        except (KeyError, TypeError):
            continue
    try:
        pp_keys = list(next_data["props"]["pageProps"].keys())
        print(f"\n  [DEBUG] no businesses found. pageProps keys: {pp_keys}", flush=True)
    except (KeyError, TypeError):
        print("\n  [DEBUG] could not read pageProps keys", flush=True)
    return []


def flatten(biz):
    loc     = biz.get("location") or {}
    contact = biz.get("contact") or {}
    cats    = biz.get("categories") or []
    ident   = biz.get("identifyingName", "")
    cat_str = "|".join(
        c.get("displayName", "") for c in cats if c.get("displayName")
    )
    return {
        "businessUnitId":            biz.get("businessUnitId", ""),
        "displayName":               biz.get("displayName", ""),
        "identifyingName":           ident,
        "profileUrl":                f"https://www.trustpilot.com/review/{ident}" if ident else "",
        "trustScore":                biz.get("trustScore", ""),
        "stars":                     biz.get("stars", ""),
        "numberOfReviews":           biz.get("numberOfReviews", ""),
        "isRecommendedInCategories": biz.get("isRecommendedInCategories", ""),
        "location_address":          loc.get("address", ""),
        "location_city":             loc.get("city", ""),
        "location_zipCode":          loc.get("zipCode", ""),
        "location_country":          loc.get("country", ""),
        "contact_website":           contact.get("website", ""),
        "contact_email":             contact.get("email", ""),
        "contact_phone":             contact.get("phone", ""),
        "categories":                cat_str,
        "logoUrl":                   biz.get("logoUrl", ""),
    }


# ── Checkpoint helpers ─────────────────────────────────────────────────────────

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    return {"last_page": 0, "seen_ids": [], "total_scraped": 0}


def save_checkpoint(last_page, seen_ids, total):
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "last_page":     last_page,
                "seen_ids":      list(seen_ids),
                "total_scraped": total,
                "saved_at":      datetime.now(timezone.utc).isoformat(),
            },
            fh,
        )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    cp         = load_checkpoint()
    start_page = cp["last_page"] + 1
    seen_ids   = set(cp["seen_ids"])
    total      = cp["total_scraped"]

    if start_page > 1:
        print(f"Resuming from page {start_page} ({total} companies already saved).\n")
    else:
        print(f"Starting : {CATEGORY_SLUG} / country={COUNTRY}")
        print(f"Output   : {OUTPUT_CSV}")
        print(f"Headless : {HEADLESS}")
        print(f"Delay    : {DELAY_MIN}–{DELAY_MAX}s between pages\n")

    csv_mode     = "a" if start_page > 1 else "w"
    write_header = csv_mode == "w"

    consecutive_empty = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        # A single persistent context keeps Cloudflare clearance cookies alive
        # across all page navigations for the duration of the run.
        context = browser.new_context(
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = context.new_page()

        with open(OUTPUT_CSV, csv_mode, newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
            if write_header:
                writer.writeheader()

            for page_num in range(start_page, MAX_PAGES + 1):
                url = BASE_URL.format(
                    slug=CATEGORY_SLUG, country=COUNTRY, page=page_num
                )
                print(f"[page {page_num:>3}/{MAX_PAGES}] ", end="", flush=True)

                nd = get_next_data(page, url)

                if nd is None:
                    print("SKIPPED")
                    consecutive_empty += 1
                    save_checkpoint(page_num, seen_ids, total)
                else:
                    businesses = parse_businesses(nd)
                    if not businesses:
                        print("EMPTY")
                        consecutive_empty += 1
                        save_checkpoint(page_num, seen_ids, total)
                    else:
                        consecutive_empty = 0
                        new = 0
                        for biz in businesses:
                            bid = biz.get("businessUnitId")
                            if bid and bid in seen_ids:
                                continue
                            if bid:
                                seen_ids.add(bid)
                            writer.writerow(flatten(biz))
                            new += 1
                        total += new
                        print(f"{new:>2} new  (total: {total})")
                        fh.flush()
                        save_checkpoint(page_num, seen_ids, total)

                if consecutive_empty >= EMPTY_STOP:
                    print(
                        f"\n{EMPTY_STOP} consecutive empty/failed pages — "
                        "assuming end of results, stopping."
                    )
                    break

                time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

        context.close()
        browser.close()

    print(f"\nDone. {total} companies written to: {OUTPUT_CSV}")
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        print("Checkpoint file removed.")


if __name__ == "__main__":
    main()
