# ── API ────────────────────────────────────────────────────────────────────────

import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["OPENROUTER_API_KEY"]  # set in .env or environment
MODEL    = "deepseek/deepseek-v4-flash"   # fast and cheap; swap to anthropic/claude-3.5-sonnet for higher quality
BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# ── Files ──────────────────────────────────────────────────────────────────────

INPUT_CSV  = "trustpilot_meta_test.csv"
OUTPUT_CSV = "trustpilot_embeddings_test.csv"
OUTPUT_COL = "embedding_text"       # new column name written to OUTPUT_CSV

# ── Processing ─────────────────────────────────────────────────────────────────

BATCH_SIZE  = 20    # items per LLM call — keep ≤ 30 for reliable structured output
CONCURRENCY = 5     # concurrent API calls; scale up if your OpenRouter tier allows
TEMPERATURE = 0.1   # low = more consistent, deterministic outputs

# ── Column mapping ─────────────────────────────────────────────────────────────
# Maps bundle field names → actual CSV column names in INPUT_CSV

COLUMNS = {
    "company_name":     "displayName",
    "url":              "contact_website",
    "categories":       "categories",
    "description":      "description",       # Trustpilot "About" free-text
    "meta_title":       "meta_title",
    "meta_description": "meta_description",  # primary; og_description is fallback
    "og_description":   "og_description",
}

# ── Sentinel for low-quality / insufficient input ──────────────────────────────
# Rows with this value in OUTPUT_COL can be filtered out before embedding.

INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

# ── Prompts ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a data enrichment assistant that converts company profile fragments into \
clean, embedding-ready descriptions for B2B software and internet companies.

Your output is used for semantic vector embeddings and company clustering. \
Produce concise, factual, information-dense text.

Guidelines:
- Length: 2-4 sentences, 40-100 words per company
- Always name the specific product/service category \
(e.g. "payroll software", "cloud storage", "email marketing platform", "e-commerce hosting")
- Include the target customer segment when clearly inferable \
(e.g. "for small businesses", "for developers", "for enterprise teams", "for consumers")
- Strip marketing superlatives: "leading", "best-in-class", "world-class", \
"innovative", "trusted", "cutting-edge", "pioneering"
- Use present tense, third person
- Prefer specific over vague: "invoicing software for freelancers" beats "business solution"
- Do not invent details absent from the input data

Low-quality rule: if the available data is too sparse to write a meaningful, \
specific description (e.g. only a domain name with no category, description, or \
title signal), output exactly the string: INSUFFICIENT_DATA\
"""

# {n} and {json_input} are substituted at runtime
BATCH_USER_TEMPLATE = """\
Process the following {n} company entries.

Return a JSON array of exactly {n} objects. Each object must have:
  "id"   — integer matching the input "id" field
  "text" — your synthesized description string, or "INSUFFICIENT_DATA"

Return only the raw JSON array, no markdown fences, no other text.

{json_input}\
"""

# {json_input} substituted at runtime — used as individual fallback
SINGLE_USER_TEMPLATE = """\
Process this company entry.

Return a JSON object with a single key "text" containing your synthesized \
description, or "INSUFFICIENT_DATA".

Return only the raw JSON object, no markdown fences, no other text.

{json_input}\
"""
