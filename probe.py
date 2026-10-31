#!/usr/bin/env python3
"""One-off: render STIGA pages in a real browser and save the HTML to probe/."""
import pathlib
from playwright.sync_api import sync_playwright
d = pathlib.Path("probe"); d.mkdir(exist_ok=True)
PAGES = {"stiga_render_sale": "https://www.stigasports.com/en/category/sale/table-tennis-bats-sale",
         "stiga_render_outlet": "https://www.stigasports.com/en/category/sale/outlet",
         "stiga_render_rubber": "https://www.stigasports.com/en/category/table-tennis/table-tennis-rubber"}
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(locale="en-US")
    for k, u in PAGES.items():
        try:
            pg.goto(u, wait_until="networkidle", timeout=60000)
            pg.wait_for_timeout(4000)
            for _ in range(4):
                pg.mouse.wheel(0, 4000); pg.wait_for_timeout(800)
            (d / f"{k}.html").write_text(pg.content())
            print(k, "ok")
        except Exception as e:
            (d / f"{k}.html").write_text(f"<!-- ERROR {e} -->"); print(k, e)
    b.close()
