#!/usr/bin/env python3
"""
Homepage meta-tag fetcher.
Reads an enriched CSV, fetches <title>, meta[description], and og:description
from each company's contact_website, and writes a new CSV with those columns appended.
Requires: pip install httpx
"""

import asyncio
import csv
import json
import os
from datetime import datetime, timezone
from html.parser import HTMLParser

import httpx

# ── Configuration ──────────────────────────────────────────────────────────────

INPUT_CSV       = "trustpilot_enriched.csv"
OUTPUT_CSV      = "trustpilot_meta.csv"
CHECKPOINT_FILE = ".meta_checkpoint.json"

CONCURRENCY = 30
TIMEOUT     = 8.0   # seconds per request
CHUNK_SIZE  = 300   # rows per checkpoint flush

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

NEW_FIELDS = ["meta_title", "meta_description", "og_description"]

# ── HTML parsing ───────────────────────────────────────────────────────────────

class MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title     = ""
        self.meta_desc = ""
        self.og_desc   = ""
        self._in_title = False
        self._done     = False  # stop after </head>

    def handle_starttag(self, tag, attrs):
        if self._done:
            return
        d = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name    = d.get("name",     "").lower()
            prop    = d.get("property", "").lower()
            content = d.get("content",  "")
            if name == "description" and not self.meta_desc:
                self.meta_desc = content
            elif prop == "og:description" and not self.og_desc:
                self.og_desc = content

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "head":
            self._done = True

    def handle_data(self, data):
        if self._in_title and not self._done:
            self.title += data


def parse_meta(html):
    parser = MetaParser()
    try:
        parser.feed(html[:60_000])  # <head> is always early; cap to avoid huge bodies
    except Exception:
        pass
    return {
        "meta_title":       parser.title.strip(),
        "meta_description": parser.meta_desc.strip(),
        "og_description":   parser.og_desc.strip(),
    }


# ── URL normalization ──────────────────────────────────────────────────────────

def normalize_url(raw):
    url = (raw or "").strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


# ── Async fetch ───────────────────────────────────────────────────────────────

EMPTY_META = {"meta_title": "", "meta_description": "", "og_description": ""}


async def fetch_row(client, sem, row):
    url = normalize_url(row.get("contact_website", ""))
    if not url:
        return EMPTY_META

    async with sem:
        try:
            resp = await client.get(url, timeout=TIMEOUT)
            ct = resp.headers.get("content-type", "")
            if ct and "html" not in ct:
                return EMPTY_META
            return parse_meta(resp.text)
        except Exception:
            return EMPTY_META


# ── Checkpoint helpers ─────────────────────────────────────────────────────────

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, encoding="utf-8") as fh:
            cp = json.load(fh)
        print(f"Checkpoint found: {cp['total_done']} rows already done, resuming.\n")
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

async def main():
    cp            = load_checkpoint()
    processed_ids = set(cp["processed_ids"])
    total_done    = cp["total_done"]

    with open(INPUT_CSV, newline="", encoding="utf-8") as fh:
        reader       = csv.DictReader(fh)
        input_rows   = list(reader)
        input_fields = reader.fieldnames or []

    output_fields = input_fields + NEW_FIELDS
    total_rows    = len(input_rows)
    remaining     = [r for r in input_rows if r["businessUnitId"] not in processed_ids]

    print(f"Input       : {INPUT_CSV} ({total_rows} rows)")
    print(f"Output      : {OUTPUT_CSV}")
    print(f"To fetch    : {len(remaining)}  (skipping {total_rows - len(remaining)} already done)")
    print(f"Concurrency : {CONCURRENCY}  |  chunk size: {CHUNK_SIZE}\n")

    csv_mode     = "a" if processed_ids else "w"
    write_header = csv_mode == "w"

    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(
        headers=HEADERS,
        follow_redirects=True,
        verify=False,           # tolerate expired/self-signed certs on company sites
        max_redirects=5,
    ) as client:
        with open(OUTPUT_CSV, csv_mode, newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=output_fields)
            if write_header:
                writer.writeheader()

            chunks_total = (len(remaining) + CHUNK_SIZE - 1) // CHUNK_SIZE

            for chunk_idx, chunk_start in enumerate(range(0, len(remaining), CHUNK_SIZE), start=1):
                chunk   = remaining[chunk_start : chunk_start + CHUNK_SIZE]
                tasks   = [fetch_row(client, sem, row) for row in chunk]
                results = await asyncio.gather(*tasks)

                for row, meta in zip(chunk, results):
                    out = {**dict(row), **meta}
                    writer.writerow(out)
                    processed_ids.add(row["businessUnitId"])
                    total_done += 1

                fh.flush()
                save_checkpoint(processed_ids, total_done)
                print(f"  chunk {chunk_idx:>3}/{chunks_total}  —  {total_done:>5}/{total_rows} rows done", flush=True)

    print(f"\nDone. {total_done} rows written to: {OUTPUT_CSV}")
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        print("Checkpoint file removed.")


if __name__ == "__main__":
    asyncio.run(main())
