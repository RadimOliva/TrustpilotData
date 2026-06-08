#!/usr/bin/env python3
"""
Diagnostic: dumps __NEXT_DATA__ and raw HTML from a Trustpilot profile page.
"""

import json
from playwright.sync_api import sync_playwright

URL = "https://www.trustpilot.com/review/divilife.com"

def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page(locale="en-US")

        page.goto(URL, wait_until="domcontentloaded", timeout=60000)

        # Give Cloudflare / JS time to fully render
        page.wait_for_timeout(8000)

        title = page.title()
        current_url = page.url
        print(f"Page title : {title}")
        print(f"Current URL: {current_url}")

        # Save full HTML so we can inspect it
        html = page.content()
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Full HTML saved to debug_page.html ({len(html):,} bytes)")

        # Try __NEXT_DATA__
        content = page.evaluate(
            "() => document.getElementById('__NEXT_DATA__')?.textContent ?? null"
        )

        if not content:
            print("\nNo __NEXT_DATA__ found.")
            print("Check debug_page.html to see what the page actually contains.")
            input("Browser staying open — press Enter to close.")
            browser.close()
            return

        print("\n__NEXT_DATA__ found, parsing…")
        nd = json.loads(content)

        # Save full JSON for inspection
        with open("debug_next_data.json", "w", encoding="utf-8") as f:
            json.dump(nd, f, indent=2)
        print("Full JSON saved to debug_next_data.json")

        pp = nd.get("props", {}).get("pageProps", {})
        print("\n=== pageProps top-level keys ===")
        for k, v in pp.items():
            vtype = type(v).__name__
            preview = ""
            if isinstance(v, str):
                preview = f" = {v[:100]!r}"
            elif isinstance(v, dict):
                preview = f" keys: {list(v.keys())}"
            elif isinstance(v, list):
                preview = f" list[{len(v)}]"
            print(f"  {k!r:45s} ({vtype}){preview}")

        bu = pp.get("businessUnit")
        if bu and isinstance(bu, dict):
            print("\n=== pageProps.businessUnit keys ===")
            for k, v in bu.items():
                vtype = type(v).__name__
                preview = ""
                if isinstance(v, str):
                    preview = f" = {v[:120]!r}"
                elif isinstance(v, dict):
                    preview = f" keys: {list(v.keys())}"
                elif isinstance(v, list):
                    preview = f" list[{len(v)}]"
                print(f"  {k!r:45s} ({vtype}){preview}")

        browser.close()

if __name__ == "__main__":
    main()
