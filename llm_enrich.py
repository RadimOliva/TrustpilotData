#!/usr/bin/env python3
"""
LLM enricher — produces embedding-ready text for each company row.
Reads INPUT_CSV, bundles signals per row, calls OpenRouter in batches,
writes OUTPUT_CSV with an embedding_text column appended.

Requires: pip install httpx
Config  : edit llm_config.py before running
"""

import asyncio
import csv
import json
import os
import re
from datetime import datetime, timezone

import httpx
import llm_config as cfg

CHECKPOINT_FILE = ".llm_checkpoint.json"

# ── Bundle builder ─────────────────────────────────────────────────────────────

def build_bundle(row):
    c    = cfg.COLUMNS
    meta = row.get(c["meta_description"], "").strip()
    og   = row.get(c["og_description"],   "").strip()
    return {
        "company":          row.get(c["company_name"],  "").strip(),
        "url":              row.get(c["url"],            "").strip(),
        "categories":       row.get(c["categories"],    "").strip(),
        "description":      row.get(c["description"],   "").strip(),
        "meta_title":       row.get(c["meta_title"],    "").strip(),
        "site_description": meta or og,   # meta primary, og fallback
    }


# ── LLM API call ───────────────────────────────────────────────────────────────

async def call_api(client, sem, messages, max_retries=3):
    """POST to OpenRouter. Returns response content string or None."""
    for attempt in range(max_retries):
        if attempt > 0:
            await asyncio.sleep(2 ** (attempt - 1))  # 1s, 2s — outside semaphore
        async with sem:
            try:
                resp = await client.post(
                    cfg.BASE_URL,
                    json={
                        "model":       cfg.MODEL,
                        "messages":    messages,
                        "temperature": cfg.TEMPERATURE,
                    },
                    timeout=30.0,
                )
                if resp.status_code == 429:
                    print(f"  [rate limit, retrying in {2**attempt}s]", flush=True)
                    continue
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as exc:
                if attempt == max_retries - 1:
                    print(f"  [API error] {exc}", flush=True)
    return None


def extract_json(text):
    """Extract the first parseable JSON array or object from a string."""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"```", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
        # Unwrap common wrapper keys LLMs sometimes add
        if isinstance(parsed, dict):
            for key in ("results", "companies", "items", "data"):
                if isinstance(parsed.get(key), list):
                    return parsed[key]
        return parsed
    except json.JSONDecodeError:
        for pattern in (r"\[[\s\S]*\]", r"\{[\s\S]*\}"):
            m = re.search(pattern, cleaned)
            if m:
                try:
                    return json.loads(m.group())
                except json.JSONDecodeError:
                    pass
    return None


# ── Single-item call (batch fallback) ─────────────────────────────────────────

async def process_single(client, sem, bundle):
    messages = [
        {"role": "system", "content": cfg.SYSTEM_PROMPT},
        {"role": "user",   "content": cfg.SINGLE_USER_TEMPLATE.format(
            json_input=json.dumps(bundle, ensure_ascii=False),
        )},
    ]
    raw    = await call_api(client, sem, messages)
    parsed = extract_json(raw)
    if isinstance(parsed, dict) and "text" in parsed:
        return str(parsed["text"]).strip() or cfg.INSUFFICIENT_DATA
    return cfg.INSUFFICIENT_DATA


# ── Batch call ─────────────────────────────────────────────────────────────────

async def process_batch(client, sem, rows):
    """
    Process a batch of rows in one LLM call.
    Falls back to per-row individual calls if the response can't be parsed
    or the array length doesn't match.
    """
    bundles = [build_bundle(row) for row in rows]
    indexed = [{"id": i, **b} for i, b in enumerate(bundles)]

    messages = [
        {"role": "system", "content": cfg.SYSTEM_PROMPT},
        {"role": "user",   "content": cfg.BATCH_USER_TEMPLATE.format(
            n=len(rows),
            json_input=json.dumps(indexed, ensure_ascii=False, indent=2),
        )},
    ]

    raw    = await call_api(client, sem, messages)
    parsed = extract_json(raw)

    if isinstance(parsed, list) and len(parsed) == len(rows):
        ordered = sorted(parsed, key=lambda x: x.get("id", 0))
        return [str(item.get("text") or cfg.INSUFFICIENT_DATA).strip() for item in ordered]

    # Fallback — individual calls for every row in this batch
    print(
        f"  [batch parse error or length mismatch — falling back to "
        f"{len(rows)} individual calls]",
        flush=True,
    )
    tasks = [process_single(client, sem, b) for b in bundles]
    return list(await asyncio.gather(*tasks))


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

    with open(cfg.INPUT_CSV, newline="", encoding="utf-8") as fh:
        reader       = csv.DictReader(fh)
        input_rows   = list(reader)
        input_fields = reader.fieldnames or []

    output_fields = input_fields + [cfg.OUTPUT_COL]
    total_rows    = len(input_rows)
    remaining     = [r for r in input_rows if r["businessUnitId"] not in processed_ids]

    total_batches = (len(remaining) + cfg.BATCH_SIZE - 1) // cfg.BATCH_SIZE

    print(f"Input       : {cfg.INPUT_CSV} ({total_rows} rows)")
    print(f"Output      : {cfg.OUTPUT_CSV}")
    print(f"Model       : {cfg.MODEL}")
    print(f"To process  : {len(remaining)}  (skipping {total_rows - len(remaining)} already done)")
    print(f"Batch size  : {cfg.BATCH_SIZE}  |  concurrency: {cfg.CONCURRENCY}")
    print(f"Total calls : ~{total_batches}\n")

    csv_mode     = "a" if processed_ids else "w"
    write_header = csv_mode == "w"

    # One round = CONCURRENCY batches processed simultaneously; checkpoint after each round
    round_size = cfg.CONCURRENCY * cfg.BATCH_SIZE

    sem = asyncio.Semaphore(cfg.CONCURRENCY)

    async with httpx.AsyncClient(
        headers={
            "Authorization": f"Bearer {cfg.API_KEY}",
            "Content-Type":  "application/json",
            "HTTP-Referer":  "https://github.com/",
            "X-Title":       "TrustpilotEnricher",
        }
    ) as client:
        with open(cfg.OUTPUT_CSV, csv_mode, newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=output_fields)
            if write_header:
                writer.writeheader()

            round_num    = 0
            total_rounds = (len(remaining) + round_size - 1) // round_size

            for round_start in range(0, len(remaining), round_size):
                round_num  += 1
                round_rows  = remaining[round_start : round_start + round_size]

                batches = [
                    round_rows[i : i + cfg.BATCH_SIZE]
                    for i in range(0, len(round_rows), cfg.BATCH_SIZE)
                ]
                tasks         = [process_batch(client, sem, batch) for batch in batches]
                batch_results = await asyncio.gather(*tasks)

                insufficient_this_round = 0
                for batch_rows, texts in zip(batches, batch_results):
                    for row, text in zip(batch_rows, texts):
                        out               = dict(row)
                        out[cfg.OUTPUT_COL] = text
                        writer.writerow(out)
                        processed_ids.add(row["businessUnitId"])
                        total_done += 1
                        if text == cfg.INSUFFICIENT_DATA:
                            insufficient_this_round += 1

                fh.flush()
                save_checkpoint(processed_ids, total_done)

                suffix = (
                    f"  ({insufficient_this_round} INSUFFICIENT_DATA)"
                    if insufficient_this_round else ""
                )
                print(
                    f"  round {round_num:>3}/{total_rounds}"
                    f"  —  {total_done:>5}/{total_rows} rows done"
                    f"{suffix}",
                    flush=True,
                )

    # Final summary
    total_insufficient = sum(
        1 for row in csv.DictReader(open(cfg.OUTPUT_CSV, encoding="utf-8"))
        if row.get(cfg.OUTPUT_COL) == cfg.INSUFFICIENT_DATA
    )
    pct = total_insufficient / total_rows * 100 if total_rows else 0

    print(f"\nDone. {total_done} rows written to: {cfg.OUTPUT_CSV}")
    print(f"INSUFFICIENT_DATA: {total_insufficient} rows ({pct:.1f}%)")

    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        print("Checkpoint file removed.")


if __name__ == "__main__":
    asyncio.run(main())
