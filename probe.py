#!/usr/bin/env python3
"""One-off: save sample shop pages to probe/ so readers can be built for them."""
import pathlib, re, requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
     "Accept-Language": "en-US,en;q=0.9"}
PAGES = {
 "megaspin_rubber_sale": "https://www.megaspin.net/store/collection.asp?id=rubber-sale",
 "megaspin_bfly_apparel": "https://www.megaspin.net/store/collection.asp?id=butterfly-apparel-sale",
 "megaspin_search_dignics": "https://www.megaspin.net/store/search.asp?q=dignics",
 "megaspin_home": "https://www.megaspin.net/store/default.asp",
 "dandoy_promotion": "https://www.dandoy-sports.com/promotion",
 "dandoy_liquidation": "https://www.dandoy-sports.com/liquidation",
 "bfly_monthly_sale": "https://shop.butterflyonline.com/shop/table-tennis-monthly-sale",
 "bfly_search_dignics": "https://shop.butterflyonline.com/search?q=dignics",
 "stiga_tt_sale": "https://www.stigasports.com/en/category/sale/table-tennis-bats-sale",
 "stiga_sale": "https://www.stigasports.com/en/category/sale",
 "donic_search_shirt": "https://www.donic.com/search?search=shirt",
 "donic_search_bluestar": "https://www.donic.com/search?search=bluestar",
 "gewo_home": "https://gewo.de/en-us",
 "gewo_sale": "https://gewo.de/en-us/sale",
 "yasaka_home": "https://www.yasakatabletennis.com/",
 "andro_shop": "https://www.andro.de/en/shop",
}
d = pathlib.Path("probe"); d.mkdir(exist_ok=True)
for k, u in PAGES.items():
    try:
        r = requests.get(u, headers=H, timeout=30)
        (d / f"{k}.html").write_text(f"<!-- {r.status_code} {r.url} -->\n" + r.text[:900000])
        print(k, r.status_code, len(r.text))
    except Exception as e:
        (d / f"{k}.html").write_text(f"<!-- ERROR {e} -->")
        print(k, "ERR", e)
