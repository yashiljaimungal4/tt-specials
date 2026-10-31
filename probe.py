#!/usr/bin/env python3
"""One-off: save sample shop pages to probe/ so readers can be built for them."""
import pathlib, re, requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
     "Accept-Language": "en-US,en;q=0.9"}
PAGES = {
 "bfly_api_sale": "https://shop.butterflyonline.com/api/items?c=739136&country=US&currency=USD&fieldset=search&language=en&n=2&commercecategoryurl=%2Fshop%2Ftable-tennis-monthly-sale&limit=60&offset=0",
 "bfly_api_q": "https://shop.butterflyonline.com/api/items?c=739136&country=US&currency=USD&fieldset=search&language=en&n=2&q=dignics&limit=20",
 "stiga_tt_sale_full": "https://www.stigasports.com/en/category/sale/table-tennis-bats-sale",
 "stiga_tt_rubbers": "https://www.stigasports.com/en/category/table-tennis/rubbers",
 "joola_eu_sale": "https://joola.fr/en/collections/vente/products.json?limit=250",
 "joola_us_outlet": "https://joola.com/collections/outlet/products.json?limit=250",
 "dandoy_bluestar": "https://www.dandoy-sports.com/catalogsearch/result/?q=bluestar+a1",
 "gewo_com": "https://gewo.com/",
}
d = pathlib.Path("probe"); d.mkdir(exist_ok=True)
for k, u in PAGES.items():
    try:
        r = requests.get(u, headers=H, timeout=30)
        (d / f"{k}.html").write_text(f"<!-- {r.status_code} {r.url} -->\n" + r.text[:4000000])
        print(k, r.status_code, len(r.text))
    except Exception as e:
        (d / f"{k}.html").write_text(f"<!-- ERROR {e} -->")
        print(k, "ERR", e)
