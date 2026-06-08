#!/usr/bin/env python3
"""
Trustpilot second-pass enricher.
Reads the first-pass CSV, fetches each company's profile page, extracts
the free-form "About" description, and writes an enriched CSV.
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

INPUT_CSV       = "trustpilot_internet_software_us.csv"
OUTPUT_CSV      = "trustpilot_enriched.csv"
CHECKPOINT_FILE = ".enrich_checkpoint.json"

DELAY_MIN    = 2.0    # seconds between requests (lower bound)
DELAY_MAX    = 4.0    # seconds between requests (upper bound)
PAGE_TIMEOUT = 30000  # ms — navigation timeout per page
HEADLESS     = False  # profile pages are more aggressively gated than category pages

# ── Description extraction ─────────────────────────────────────────────────────

def extract_description(next_data):
    # Primary location confirmed via __NEXT_DATA__ inspection:
    # sidebarData.infoBusinessUnitBox.descriptionTextPlain (HTML-stripped version)
    # descriptionText is the raw HTML alternative — we prefer the plain variant.
    candidates = [
        lambda d: d["props"]["pageProps"]["sidebarData"]["infoBusinessUnitBox"]["descriptionTextPlain"],
        lambda d: d["props"]["pageProps"]["sidebarData"]["infoBusinessUnitBox"]["descriptionText"],
    ]
    for fn in candidates:
        try:
            val = fn(next_data)
            if isinstance(val, str) and val.strip():
                # Collapse runs of whitespace/newlines into single spaces
                import re
                return re.sub(r"\s+", " ", val).strip()
        except (KeyError, TypeError):
            continue
    return ""


def get_description(page, profile_url):
    """Navigate to a company profile and return its description (or '')."""
    try:
        page.goto(profile_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
    except PlaywrightTimeout:
        print("  [timeout]", flush=True)
        return None  # None = failed (skip/retry), "" = fetched but no description

    try:
        content = page.evaluate(
            "() => document.getElementById('__NEXT_DATA__')?.textContent ?? null"
        )
    except Exception as exc:
        print(f"  [evaluate error] {exc}", flush=True)
        return None

    if not content:
        current = page.url
        print(f"  [no __NEXT_DATA__] landed on: {current}", flush=True)
        return None

    try:
        nd = json.loads(content)
    except json.JSONDecodeError as exc:
        print(f"  [JSON error] {exc}", flush=True)
        return None

    return extract_description(nd)


# ── Checkpoint helpers ─────────────────────────────────────────────────────────

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, encoding="utf-8") as fh:
            cp = json.load(fh)
        print(
            f"Checkpoint found: {cp['total_done']} rows already enriched, "
            f"resuming.\n"
        )
        return cp
    return {"processed_ids": [], "total_done": 0}


def save_checkpoint(processed_ids, total_done):
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "processed_ids": list(processed_ids),
                "total_done":    total_done,
                "saved_at":      datetime.now(timezone.utc).isoformat(),
            },
            fh,
        )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    cp            = load_checkpoint()
    processed_ids = set(cp["processed_ids"])
    total_done    = cp["total_done"]

    # Read all input rows upfront (8k rows, trivially small in memory).
    with open(INPUT_CSV, newline="", encoding="utf-8") as fh:
        reader     = csv.DictReader(fh)
        input_rows = list(reader)
        input_fields = reader.fieldnames or []

    output_fields = input_fields + ["description"]
    total_rows    = len(input_rows)
    remaining     = [r for r in input_rows if r["businessUnitId"] not in processed_ids]

    print(f"Input    : {INPUT_CSV} ({total_rows} rows)")
    print(f"Output   : {OUTPUT_CSV}")
    print(f"To fetch : {len(remaining)} (skipping {total_rows - len(remaining)} already done)")
    print(f"Headless : {HEADLESS}")
    print(f"Delay    : {DELAY_MIN}–{DELAY_MAX}s between requests\n")

    csv_mode     = "a" if processed_ids else "w"
    write_header = csv_mode == "w"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = context.new_page()

        with open(OUTPUT_CSV, csv_mode, newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=output_fields)
            if write_header:
                writer.writeheader()

            for i, row in enumerate(remaining, start=1):
                bid         = row["businessUnitId"]
                name        = row["displayName"]
                profile_url = row["profileUrl"]

                print(
                    f"[{total_done + 1:>5}/{total_rows}] {name[:45]:<45} ",
                    end="",
                    flush=True,
                )

                desc = get_description(page, profile_url)

                if desc is None:
                    # Navigation failed — write row with empty description and move on.
                    # The company will not be retried on resume (it's checkpointed).
                    desc = ""
                    print("FAILED (saved with empty description)")
                else:
                    preview = (desc[:60] + "…") if len(desc) > 60 else desc or "(no description)"
                    print(preview)

                out_row = dict(row)
                out_row["description"] = desc
                writer.writerow(out_row)
                fh.flush()

                processed_ids.add(bid)
                total_done += 1
                save_checkpoint(processed_ids, total_done)

                time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

        context.close()
        browser.close()

    print(f"\nDone. {total_done} rows written to: {OUTPUT_CSV}")
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        print("Checkpoint file removed.")


if __name__ == "__main__":
    main()
