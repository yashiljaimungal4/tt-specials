#!/usr/bin/env python3
"""One-off: visit candidate shops and report platform + sale links to probe.json."""
import json
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
     "Accept-Language": "en-US,en;q=0.9"}
CANDIDATES = [
    "https://www.megaspin.net/store/", "https://www.megaspin.net/default.asp",
    "https://dandoy-sports.com/en/", "https://dandoy-sports.com/",
    "https://shop.butterflyonline.com/", "https://www.butterfly.tt/", "https://butterfly-shop.de/",
    "https://www.donic.com/", "https://www.donic-shop.de/",
    "https://stigasports.com/", "https://www.stigaus.com/",
    "https://www.yasaka.se/", "https://www.yasaka.co.jp/", "https://www.yasakatabletennis.com/",
    "https://www.andro.de/", "https://andro.de/en/",
    "https://joola.com/", "https://joola.fr/en", "https://www.joola.de/",
    "https://www.gewo.com/", "https://www.gewo-shop.com/", "https://gewo.de/",
]
SALE_WORDS = re.compile(r"sale|outlet|clearance|special|promo|angebot|sonder|deal|discount|aktion|solde|offer|reduz", re.I)


def detect(html, headers):
    h = html[:400000].lower()
    tags = []
    for name, pat in [("shopify", "cdn.shopify.com"), ("woocommerce", "woocommerce"), ("magento", "mage/cookies"),
                      ("magento", "magento"), ("bigcommerce", "bigcommerce"), ("shopware", "shopware"),
                      ("prestashop", "prestashop"), ("oxid", "oxid"), ("wix", "wix.com"), ("squarespace", "squarespace"),
                      ("jtl", "jtl-shop"), ("centra", "centra"), ("nextjs", "__next"), ("asp", ".asp")]:
        if pat in h and name not in tags:
            tags.append(name)
    gen = re.search(r'<meta name="generator" content="([^"]+)"', html, re.I)
    if gen:
        tags.append("generator:" + gen.group(1)[:60])
    return tags


out = []
for url in CANDIDATES:
    rec = {"url": url}
    try:
        r = requests.get(url, headers=H, timeout=25, allow_redirects=True)
        rec.update(status=r.status_code, final=r.url, server=r.headers.get("server", ""), platform=detect(r.text, r.headers))
        soup = BeautifulSoup(r.text, "html.parser")
        rec["title"] = (soup.title.get_text(strip=True) if soup.title else "")[:100]
        host = urlparse(r.url).netloc
        links = []
        for a in soup.select("a[href]"):
            href, txt = a.get("href", ""), a.get_text(" ", strip=True)[:60]
            full = urljoin(r.url, href)
            if urlparse(full).netloc.endswith(host.replace("www.", "")) and (SALE_WORDS.search(href) or SALE_WORDS.search(txt)):
                links.append([txt, full])
        seen, uniq = set(), []
        for t, l in links:
            if l not in seen:
                seen.add(l)
                uniq.append([t, l])
        rec["sale_links"] = uniq[:25]
        # search form
        f = soup.select_one("form[action*=search], form[role=search], form input[name=q], form input[name=s], form input[name=search]")
        if f:
            form = f if f.name == "form" else f.find_parent("form")
            if form:
                rec["search_form"] = {"action": urljoin(r.url, form.get("action", "")),
                                      "inputs": [i.get("name") for i in form.select("input[name]")][:6]}
        base = f"{urlparse(r.url).scheme}://{host}"
        for probe, path in [("shopify_products", "/products.json?limit=1"),
                            ("woo_api", "/wp-json/wc/store/v1/products?per_page=1"),
                            ("sitemap", "/sitemap.xml")]:
            try:
                p = requests.get(base + path, headers=H, timeout=20)
                rec[probe] = [p.status_code, p.headers.get("content-type", "")[:40], p.text[:160]]
            except Exception as e:
                rec[probe] = ["err", str(e)[:80]]
    except Exception as e:
        rec["error"] = str(e)[:200]
    out.append(rec)
    print(url, rec.get("status"), rec.get("platform"), len(rec.get("sale_links", [])))

json.dump(out, open("probe.json", "w"), indent=1, ensure_ascii=False)
