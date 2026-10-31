#!/usr/bin/env python3
"""Table tennis specials monitor for Table Tennis 11 and Racketlon Sports.

Runs on GitHub Actions 5x a day. Sends a phone alert (through the deals app) only for
specials it hasn't alerted about before. State lives in state.json.

Usage:
  python monitor.py            # normal run (sends alerts, updates state.json)
  python monitor.py --dry-run  # print what it finds, send nothing, save nothing
  python monitor.py --test-alert  # send one test notification to your phone
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus, urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
CFG = json.loads((ROOT / "config.json").read_text())
STATE_FILE = ROOT / "state.json"
TZ = ZoneInfo(CFG["timezone"])
NOW = datetime.now(TZ)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
DRY = "--dry-run" in sys.argv
LOG = []


def log(msg):
    LOG.append(str(msg))
    print(msg)


def get(url, **kw):
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30, **kw)
            if r.status_code == 200:
                return r
            log(f"  HTTP {r.status_code} for {url}")
            if r.status_code in (403, 404):
                return None
        except requests.RequestException as e:
            log(f"  error fetching {url}: {e}")
        time.sleep(3)
    return None


# ---------------------------------------------------------------- money
PRICE_RE = re.compile(r"(€|R|\$|£)\s?([0-9][0-9\s.,]*[0-9]|[0-9])")


def parse_money(text):
    """'€31.16' -> ('EUR', 31.16); 'R1 299,00' -> ('ZAR', 1299.0)."""
    m = PRICE_RE.search(text or "")
    if not m:
        return None
    sym, num = m.group(1), m.group(2).replace(" ", "").replace(" ", "")
    if "," in num and "." in num:
        num = num.replace(",", "") if num.rfind(".") > num.rfind(",") else num.replace(".", "").replace(",", ".")
    elif "," in num:
        num = num.replace(",", ".") if len(num.split(",")[-1]) == 2 else num.replace(",", "")
    try:
        val = float(num)
    except ValueError:
        return None
    return ({"€": "EUR", "R": "ZAR", "$": "USD", "£": "GBP"}[sym], val)


_rates = {}


def to_zar(cur, amount):
    if cur == "ZAR":
        return amount
    if cur not in _rates:
        rate = None
        r = get(f"https://open.er-api.com/v6/latest/{cur}")
        if r:
            try:
                rate = r.json()["rates"]["ZAR"]
            except Exception:
                pass
        _rates[cur] = rate or {"EUR": 20.5, "USD": 18.0, "GBP": 23.5}.get(cur, 20.0)
        if not rate:
            log(f"  using fallback {cur}->ZAR rate {_rates[cur]}")
    return amount * _rates[cur]


def fmt(cur, amount):
    sym = {"EUR": "€", "ZAR": "R", "USD": "$", "GBP": "£"}[cur]
    s = f"{sym}{amount:,.2f}"
    if cur != "ZAR":
        s += f" (~R{to_zar(cur, amount):,.0f})"
    return s


# ---------------------------------------------------------------- matching
WL = CFG["watchlist"]


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def matches(name, rule):
    n = " " + norm(name) + " "
    ok = all(f" {norm(t)} " in n or norm(t) in n.replace(" ", "") for t in rule["must_contain"])
    bad = any(f" {norm(t)} " in n for t in rule.get("must_not_contain", []))
    return ok and not bad


def has_kw(name, kws):
    n = " " + (name or "").lower() + " "
    return any(k in n for k in kws)


NOT_GEAR = ["case", "bag", "protect", "towel", "ball", "net", "table ", "robot", "pickleball", "padel", "tennis racket",
            "glue", "cleaner", "tape", "cover", "rucksack", "backpack", "bottle", "keychain", "gift card"]


def is_shoe(name):
    return has_kw(name, WL["shoe_keywords"]) and not has_kw(name, ["bag", "lace", "sock", "pickleball", "padel"])


def is_clothing(name):
    return has_kw(name, WL["clothing_keywords"]) and not is_shoe(name) and not has_kw(name, NOT_GEAR)


def classify(name):
    """Which watchlist entry an item belongs to: ('rubber', label) / ('shoes', ...) / ('clothing', ...) / None."""
    for rule in WL["rubbers"]:
        if matches(name, rule):
            return "rubber", rule["label"]
    if is_shoe(name):
        return "shoes", "Shoes"
    if is_clothing(name):
        return "clothing", "Clothing"
    return None


def is_tt(i):
    t = (i["name"] + " " + i.get("cats", "")).lower()
    return "table tennis" in t or "tischtennis" in t or "ping pong" in t or has_kw(i["name"], WL["tt_brands"])


# ---------------------------------------------------------------- readers
def end_of_week():
    """Sunday 23:59 SA time - when weekly specials (Monday-Sunday) end."""
    days = (6 - NOW.weekday()) % 7
    return (NOW + timedelta(days=days)).replace(hour=23, minute=59, second=0, microsecond=0)


def item(name, url, special, regular=None, image="", in_stock=True, cats="", all_special=False):
    on_sale = bool(special and special[1] > 0 and (all_special or (regular and regular[1] > special[1] + 0.001)))
    if regular and special and regular[1] <= special[1] + 0.001:
        regular = None
    return {"name": name.strip(), "url": url, "special": special, "regular": regular, "image": image,
            "in_stock": in_stock, "cats": cats, "on_sale": on_sale}


def magento_list(html, base, all_special=False):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for el in soup.select("li.product-item, div.product-item, li.item.product"):
        a = el.select_one("a.product-item-link") or el.select_one(".product-item-name a") or el.select_one("a[href]")
        if not a:
            continue
        text = el.get_text(" ", strip=True)
        special = regular = None
        m = re.search(r"(?:Special Price|As low as|Starting at|Sale Price)\s*([€R$£]\s?[0-9.,\s]+)", text, re.I)
        m2 = re.search(r"(?:Regular Price|Was)\s*([€R$£]\s?[0-9.,\s]+)", text, re.I)
        if m:
            special = parse_money(m.group(1))
        if m2:
            regular = parse_money(m2.group(1))
        if not special:
            fp = el.select_one('[data-price-type="finalPrice"] .price, .special-price .price, .price')
            special = parse_money(fp.get_text()) if fp else None
        if not regular:
            op = el.select_one('[data-price-type="oldPrice"] .price, .old-price .price')
            regular = parse_money(op.get_text()) if op else None
        img = el.select_one("img.product-image-photo") or el.select_one("img")
        image = (img.get("data-src") or img.get("src") or "") if img else ""
        out.append(item(a.get_text(" ", strip=True), urljoin(base, a.get("href", "")), special, regular,
                        urljoin(base, image) if image else "",
                        "not in stock" not in text.lower() and "out of stock" not in text.lower(), all_special=all_special))
    return out


def read_magento(st):
    """Table Tennis 11 / Dandoy: sale pages + searches for the watchlist rubbers and shoes."""
    hits, ok = [], False
    for page in st["sale_pages"]:
        r = get(st["base"] + page["path"])
        if not r:
            continue
        ok = True
        items = magento_list(r.text, r.url, all_special=page.get("all_special", False))
        log(f"  {st['name']} {page['path']}: {len(items)} products, {sum(i['on_sale'] for i in items)} on special")
        for i in items:
            i["where"] = page["where"]
        hits += items
    searches = [r["search"] for r in WL["rubbers"]] + st.get("extra_searches", [])
    for q in searches:
        r = get(st["base"] + "/catalogsearch/result/?q=" + quote_plus(q))
        if not r:
            continue
        ok = True
        items = magento_list(r.text, r.url)
        for i in items:
            i["where"] = "product"
        hits += items
    return hits, ok


def read_woo(st):
    """Racketlon (WooCommerce store API)."""
    hits, ok = [], False
    for q in [r["search"] for r in WL["rubbers"]] + st.get("searches", []):
        r = get(f"{st['base']}/wp-json/wc/store/v1/products", params={"search": q, "per_page": 50})
        if not r or "json" not in r.headers.get("content-type", ""):
            continue
        ok = True
        for p in r.json():
            pr = p.get("prices", {})
            mu = 10 ** int(pr.get("currency_minor_unit", 2))
            cur = pr.get("currency_code", "ZAR")
            price, reg = int(pr.get("price") or 0) / mu, int(pr.get("regular_price") or 0) / mu
            imgs = p.get("images") or []
            i = item(BeautifulSoup(p.get("name", ""), "html.parser").get_text(), p.get("permalink", ""),
                     (cur, price), (cur, reg) if reg else None,
                     (imgs[0].get("thumbnail") or imgs[0].get("src", "")) if imgs else "",
                     p.get("is_in_stock", True), " ".join(c.get("name", "") for c in p.get("categories", [])))
            i["on_sale"] = i["on_sale"] and bool(p.get("on_sale"))
            i["where"] = "product"
            hits.append(i)
    log(f"  {st['name']}: {len(hits)} products checked, {sum(i['on_sale'] for i in hits)} on special")
    return hits, ok


def read_megaspin(st):
    hits, ok = [], False
    for cid in st["collections"]:
        url = f"{st['base']}/store/collection.asp?id={cid}"
        r = get(url)
        if not r:
            continue
        ok = True
        soup = BeautifulSoup(r.text, "html.parser")
        n = 0
        for c in soup.select(".product-card"):
            a = c.select_one(".product-name a")
            pb = c.select_one(".product-price")
            if not a or not pb:
                continue
            old = pb.select_one("s")
            regular = parse_money(old.get_text()) if old else None
            if old:
                old.extract()
            special = parse_money(pb.get_text("", strip=True))
            img = c.select_one(".product-image img")
            i = item(a.get_text(" ", strip=True), urljoin(url, a.get("href", "")), special, regular,
                     img.get("src", "") if img else "", all_special=True)
            i["where"] = "sale"
            hits.append(i)
            n += 1
        log(f"  {st['name']} {cid}: {n} products")
    return hits, ok


def read_suitecommerce(st):
    """Butterfly US (NetSuite): everything in the monthly-sale category is on special."""
    hits, ok, offset = [], False, 0
    while offset < 600:
        r = get(f"{st['base']}/api/items", params={"c": st["company"], "country": "US", "currency": "USD", "fieldset": "search",
                                                   "language": "en", "n": 2, "commercecategoryurl": st["category"],
                                                   "limit": 100, "offset": offset})
        if not r:
            break
        ok = True
        d = r.json()
        for it in d.get("items", []):
            price = (it.get("onlinecustomerprice_detail") or {}).get("onlinecustomerprice") or it.get("onlinecustomerprice") or 0
            img = ((it.get("itemimages_detail") or {}).get("main") or {}).get("url", "")
            i = item(it.get("storedisplayname2") or it.get("displayname", ""), f"{st['base']}/{it.get('urlcomponent', '')}",
                     ("USD", float(price)), None, img.replace(" ", "%20"), it.get("isinstock", True), all_special=True)
            i["where"] = "monthly"
            hits.append(i)
        offset += 100
        if offset >= d.get("total", 0):
            break
    log(f"  {st['name']}: {len(hits)} sale items")
    return hits, ok


def read_shopify(st):
    """JOOLA shops: whole catalogue via products.json; on special when compare-at price > price."""
    hits, ok = [], False
    for page in range(1, 9):
        r = get(f"{st['base']}/products.json", params={"limit": 250, "page": page})
        if not r or "json" not in r.headers.get("content-type", ""):
            break
        ok = True
        ps = r.json().get("products", [])
        for p in ps:
            ptype = (p.get("product_type") or "") + " " + " ".join(p.get("tags", []) if isinstance(p.get("tags"), list) else [p.get("tags") or ""])
            if st.get("type_must_contain") and not any(t.lower() in ptype.lower() for t in st["type_must_contain"]):
                continue
            if has_kw(ptype + " " + p.get("title", ""), ["pickleball", "padel"]):
                continue
            vs = p.get("variants") or [{}]
            best = min(vs, key=lambda v: float(v.get("price") or 1e9))
            price = float(best.get("price") or 0)
            cmp_ = max(float(v.get("compare_at_price") or 0) for v in vs)
            imgs = p.get("images") or []
            i = item(p.get("title", ""), f"{st['base']}/products/{p.get('handle', '')}", (st["currency"], price),
                     (st["currency"], cmp_) if cmp_ else None, imgs[0].get("src", "") if imgs else "",
                     any(v.get("available", True) for v in vs), ptype)
            i["where"] = "sale"
            hits.append(i)
        if len(ps) < 250:
            break
    log(f"  {st['name']}: {len(hits)} table tennis products, {sum(i['on_sale'] for i in hits)} on special")
    return hits, ok


def read_shopware(st):
    """Donic: search for each watchlist item / clothing / shoes; on special when a list price is shown."""
    hits, ok = [], False
    for q in [r["search"] for r in WL["rubbers"]] + st.get("searches", []):
        r = get(f"{st['base']}/search", params={"search": q})
        if not r:
            continue
        ok = True
        soup = BeautifulSoup(r.text, "html.parser")
        for b in soup.select(".product-box"):
            n = b.select_one(".product-name")
            if not n:
                continue
            pp = b.select_one(".product-price")
            lp = b.select_one(".list-price-price, .list-price .list-price-price, .product-price .list-price")
            regular = parse_money(lp.get_text(" ", strip=True)) if lp else None
            if lp:
                lp.extract()
            special = parse_money(pp.get_text(" ", strip=True)) if pp else None
            img = b.select_one("img")
            i = item(n.get_text(" ", strip=True), urljoin(st["base"], n.get("href", "")), special, regular,
                     (img.get("src") or img.get("data-src") or "") if img else "")
            i["where"] = "product"
            hits.append(i)
    log(f"  {st['name']}: {len(hits)} products checked, {sum(i['on_sale'] for i in hits)} on special")
    return hits, ok


def read_browser_stiga(st):
    """STIGA: pages build their product grid with JavaScript, so render them in a headless browser."""
    hits, ok = [], False
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("  playwright not installed - skipping STIGA")
        return hits, False
    price_re = re.compile(r"^([0-9][0-9.,]*)\s*(EUR|SEK|USD|GBP)$")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(locale="en-US")
        for page in st["pages"]:
            url = st["base"] + page["path"]
            try:
                pg.goto(url, wait_until="networkidle", timeout=60000)
                pg.wait_for_timeout(3000)
                for _ in range(4):
                    pg.mouse.wheel(0, 4000)
                    pg.wait_for_timeout(700)
                html = pg.content()
            except Exception as e:
                log(f"  {st['name']} {page['path']}: {e}")
                continue
            ok = True
            soup = BeautifulSoup(html, "html.parser")
            n = 0
            for a in soup.select('a[href*="/product/"]'):
                parts = [x for x in a.get_text(" | ", strip=True).split(" | ") if x]
                prices = [(i, price_re.match(x)) for i, x in enumerate(parts) if price_re.match(x)]
                if not prices:
                    continue
                first = prices[0][0]
                name = parts[first - 2] if first >= 2 else parts[0]
                cur = {"EUR": "EUR", "SEK": "SEK", "USD": "USD", "GBP": "GBP"}[prices[0][1].group(2)]
                val = lambda m: float(m.group(1).replace(",", ""))
                special = (cur, val(prices[0][1]))
                regular = (cur, val(prices[1][1])) if len(prices) > 1 else None
                img = a.select_one("img")
                i = item("STIGA " + name, urljoin(st["base"], a.get("href", "")), special, regular,
                         urljoin(st["base"], img.get("src", "")) if img else "", all_special=page.get("all_special", False))
                i["where"] = page.get("where", "sale")
                hits.append(i)
                n += 1
            log(f"  {st['name']} {page['path']}: {n} products")
        b.close()
    return hits, ok


READERS = {"magento": read_magento, "woo": read_woo, "megaspin": read_megaspin,
           "suitecommerce": read_suitecommerce, "shopify": read_shopify, "shopware": read_shopware,
           "stiga": read_browser_stiga}


def check_store(st):
    raw, ok = READERS[st["type"]](st)
    hits, seen = [], set()
    cap = st.get("clothing_max_zar", WL.get("clothing_max_zar"))
    for i in raw:
        if not i["on_sale"] or i["url"] in seen:
            continue
        c = classify(i["name"])
        if not c:
            continue
        kind, watch = c
        if kind in ("clothing", "shoes") and st.get("needs_tt_check") and not is_tt(i):
            continue
        if kind == "clothing" and cap and to_zar(*i["special"]) > cap:
            continue
        seen.add(i["url"])
        where = i.get("where", "")
        end, et = None, {"weekly": "weekly special", "clearance": "clearance - while stock lasts",
                         "monthly": "monthly sale", "promo": "weekly special"}.get(where, "sale - no end date given")
        if where == "weekly" and st.get("weekly_ends_sunday"):
            end = end_of_week()
            et = f"ends Sun {end:%d %b} at midnight"
        hits.append(dict(i, store=st["name"], kind=kind, watch=watch if kind == "rubber" else
                         (f"Clothing ≤R{cap}" if (kind == "clothing" and cap) else watch), end=end, end_text=et))
    return hits, ok


# ---------------------------------------------------------------- alerts
import os

APP_URL = CFG.get("app_url", "./")


def load_subscriptions():
    f = ROOT / "subscriptions.json"
    subs = json.loads(f.read_text()) if f.exists() else []
    return [x["subscription"] if "subscription" in x else x for x in subs]


def notify(title, body, click=None, tags="", priority="default", image=None, tag=None):
    """Send a notification to every phone that enabled alerts in the app."""
    payload = {"title": title, "body": body, "url": click or APP_URL, "image": image or "",
               "tag": tag or title, "urgent": priority == "high"}
    if DRY:
        print(f"\n[DRY RUN] ALERT: {title}\n{body}\n")
        return
    key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    subs = load_subscriptions()
    if not key or not subs:
        log(f"  (no {'signing key' if not key else 'phones subscribed'} - alert not sent: {title})")
        return
    from pywebpush import webpush, WebPushException
    data = json.dumps(payload)
    if len(data.encode()) > 3500:
        payload["body"] = payload["body"][:1500] + "…"
        data = json.dumps(payload)
    for sub in subs:
        try:
            webpush(subscription_info=sub, data=data, vapid_private_key=key,
                    vapid_claims={"sub": CFG.get("vapid_subject", "https://github.com")}, ttl=86400,
                    headers={"Urgency": "high" if priority == "high" else "normal"})
            log(f"  alert sent: {title}")
        except WebPushException as e:
            log(f"  alert failed ({getattr(e.response, 'status_code', '?')}): {e}")


def write_app_data(hits, store_ok):
    deals = []
    for h in hits:
        cur, sp = h["special"]
        deals.append({
            "id": re.sub(r"[^a-z0-9]+", "-", (h["store"] + "-" + h["url"].rsplit("/", 1)[-1]).lower()).strip("-")[:80],
            "store": h["store"], "kind": h["kind"], "watch": h["watch"], "name": h["name"], "url": h["url"],
            "image": h.get("image", ""),
            "price_zar": round(to_zar(cur, sp)), "was_zar": round(to_zar(*h["regular"])) if h.get("regular") else None,
            "price_orig": fmt(*h["special"]).split(" (")[0] if cur != "ZAR" else None,
            "pct": pct(h), "end": h["end"].isoformat() if h.get("end") else None, "end_text": h["end_text"],
            "in_stock": h.get("in_stock", True), "where": h.get("where", ""),
            "first_seen": h.get("first_seen") or NOW.isoformat(),
        })
    order = {"rubber": 0, "shoes": 1, "clothing": 2}
    deals.sort(key=lambda d: (order.get(d["kind"], 9), -d["pct"]))
    out = {"updated": NOW.isoformat(), "stores": store_ok, "deals": deals,
           "watchlist": [r["label"] for r in WL["rubbers"]] + [f"Clothing ≤R{WL['clothing_max_zar']}", "Shoes"],
           "store_list": [{"name": st["name"], "country": st.get("country", "")} for st in CFG["stores"]]}
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "deals.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))


def pct(i):
    return round(100 * (1 - i["special"][1] / i["regular"][1])) if i.get("regular") else 0


def line(i):
    s = f"{i['name']}: {fmt(*i['special'])}"
    if i.get("regular"):
        s += f" (was {fmt(*i['regular'])}, -{pct(i)}%)"
    s += f" — {i['end_text']}"
    if not i.get("in_stock", True):
        s += " [out of stock]"
    return s


def main():
    if "--test-alert" in sys.argv:
        notify("Alerts are on ✅", "You'll be told here when your gear goes on special.", tag="test")
        return

    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"alerted": {}, "fails": {}}
    end_date = datetime.fromisoformat(CFG["monitor_end_date"]).date()
    if NOW.date() > end_date:
        if not state.get("ended"):
            notify("Table tennis monitor ended", f"Your monitor reached its end date ({end_date:%d %b %Y}). "
                   "Change monitor_end_date in config.json to keep it running.")
            state["ended"] = True
            if not DRY:
                STATE_FILE.write_text(json.dumps(state, indent=1))
        return

    log(f"Run at {NOW:%Y-%m-%d %H:%M} SAST")
    all_hits, store_ok = [], {}
    for st in CFG["stores"]:
        store = st["name"]
        log(f"Checking {store}...")
        try:
            hits, ok = check_store(st)
        except Exception as e:
            log(f"  {store} crashed: {e!r}")
            hits, ok = [], False
        all_hits += hits
        store_ok[store] = ok
        fails = state["fails"].get(store, 0)
        if ok:
            state["fails"][store] = 0
        else:
            state["fails"][store] = fails + 1
            if state["fails"][store] == 3:  # warn once after 3 failed runs in a row
                notify(f"Can't read {store}", f"The monitor couldn't read {store} for 3 checks in a row. It will keep trying.",
                       tag="warn-" + store)

    # dedupe
    uniq = {}
    for h in all_hits:
        uniq.setdefault((h["store"], h["url"]), h)
    hits = list(uniq.values())

    alerted = state["alerted"]
    new, last_day = [], []
    for h in hits:
        key = f"{h['store']}|{h['url']}|{h['special'][1]:.2f}|{h['end'].date() if h['end'] else ''}"
        if key in alerted:
            h["first_seen"] = alerted[key]["first_seen"]
        if key not in alerted:
            new.append(h)
            alerted[key] = {"first_seen": NOW.isoformat(), "end": h["end"].isoformat() if h["end"] else None}
        elif h["end"] and h["end"].date() == NOW.date() and h["kind"] != "clothing" and not alerted[key].get("lastday"):
            last_day.append(h)
            alerted[key]["lastday"] = True

    # alerts: one per watchlist rubber (high priority), one bundled for shoes / clothing
    for h in [h for h in new if h["kind"] == "rubber"]:
        body = f"R{to_zar(*h['special']):,.0f}"
        if h.get("regular"):
            body += f"  (was R{to_zar(*h['regular']):,.0f}, −{pct(h)}%)"
        body += f"\n{h['store']} · {h['end_text']}"
        notify(f"{h['watch']} is on special", body, click=h["url"], priority="high",
               image=h.get("image"), tag=h["url"])
    for kind in ("shoes", "clothing"):
        group = sorted([h for h in new if h["kind"] == kind], key=lambda h: -pct(h))
        if group:
            n = len(group)
            top = group[0]
            body = f"Best: {top['name']} — R{to_zar(*top['special']):,.0f} (−{pct(top)}%)"
            if n > 1:
                body += f"\n+{n - 1} more. Tap to see them all."
            notify(f"{n} new {kind} special{'s' if n > 1 else ''}", body, click=f"{APP_URL}#{kind}",
                   image=top.get("image"), tag=kind)
    if last_day:
        names = ", ".join(h["name"] for h in last_day[:3]) + (f" +{len(last_day) - 3}" if len(last_day) > 3 else "")
        notify("Last day — specials end tonight", names, click=APP_URL, priority="high", tag="lastday")

    # forget alerts older than 60 days so a returning special alerts again
    cutoff = NOW - timedelta(days=60)
    state["alerted"] = {k: v for k, v in alerted.items() if datetime.fromisoformat(v["first_seen"]) > cutoff}
    state["last_run"] = NOW.isoformat()
    log(f"Done: {len(hits)} watchlist specials live, {len(new)} new, {len(last_day)} last-day reminders.")
    for h in hits:
        log(f"  * {h['store']} | {h['watch']} | {line(h)}")
    write_app_data(hits, store_ok)
    (ROOT / "last_run.log").write_text("\n".join(LOG) + "\n")
    if not DRY:
        STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
