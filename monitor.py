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


def is_clothing(name):
    return has_kw(name, CFG["clothing_keywords"]) and not has_kw(name, CFG["shoe_keywords"]) \
        and not has_kw(name, ["case", "bag", "protect", "towel", "ball"])


def is_shoe(name):
    return has_kw(name, CFG["shoe_keywords"]) and not has_kw(name, ["bag", "lace"])


# ---------------------------------------------------------------- TT11 (Magento)
def tt11_end_of_week():
    """TT11 weekly specials run Monday -> Sunday night."""
    days = (7 - NOW.weekday()) % 7 or 7
    end = (NOW + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return end - timedelta(minutes=1)  # Sunday 23:59


def parse_magento_list(html, base):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for el in soup.select("li.product-item, div.product-item, li.item.product"):
        a = el.select_one("a.product-item-link") or el.select_one(".product-item-name a") or el.select_one("a[href]")
        if not a:
            continue
        name = a.get_text(" ", strip=True)
        url = urljoin(base, a.get("href", ""))
        text = el.get_text(" ", strip=True)
        special = regular = None
        # Magento renders hidden labels: "Special Price €x Regular Price €y" / "As low as €x Regular Price €y"
        m = re.search(r"(?:Special Price|As low as|Sale Price)\s*([€R$£]\s?[0-9.,\s]+)", text, re.I)
        m2 = re.search(r"(?:Regular Price|Was)\s*([€R$£]\s?[0-9.,\s]+)", text, re.I)
        if m:
            special = parse_money(m.group(1))
        if m2:
            regular = parse_money(m2.group(1))
        if not special:
            fp = el.select_one('[data-price-type="finalPrice"] .price, .special-price .price')
            special = parse_money(fp.get_text()) if fp else None
        if not regular:
            op = el.select_one('[data-price-type="oldPrice"] .price, .old-price .price')
            regular = parse_money(op.get_text()) if op else None
        on_sale = bool(special and regular and regular[1] > special[1] + 0.001)
        img = el.select_one("img.product-image-photo") or el.select_one("img")
        image = (img.get("data-src") or img.get("src") or "") if img else ""
        items.append({"name": name, "url": url, "special": special, "regular": regular, "image": urljoin(base, image) if image else "",
                      "on_sale": on_sale, "in_stock": "not in stock" not in text.lower()
                      and "out of stock" not in text.lower()})
    return items


def tt11_page(path_or_url):
    base = CFG["tt11"]["base"]
    url = path_or_url if path_or_url.startswith("http") else base + path_or_url
    r = get(url)
    if not r:
        return None
    items = parse_magento_list(r.text, url)
    log(f"  TT11 {url}: {len(items)} products, {sum(i['on_sale'] for i in items)} on special")
    return items


def check_tt11():
    t = CFG["tt11"]
    hits, ok = [], False
    weekly_end = tt11_end_of_week()

    sale_items = []
    for p in t["sale_pages"]:
        items = tt11_page(p)
        if items is not None:
            ok = True
            for i in items:
                i["where"] = "weekly" if "special" in p else "clearance"
            sale_items += items

    def end_text(i):
        if i.get("where") == "weekly":
            return weekly_end, f"ends Sun {weekly_end:%d %b} at midnight"
        if i.get("where") == "clearance":
            return None, "clearance - while stock lasts"
        return None, "no end date shown"

    # 1+2: watchlist rubbers (sale pages + search, in case of hidden specials)
    for rule in t["rubbers"]:
        found = [i for i in sale_items if i["on_sale"] and matches(i["name"], rule)]
        res = tt11_page("/catalogsearch/result/?q=" + quote_plus(rule["search"]))
        if res is not None:
            ok = True
            seen_urls = {i["url"] for i in found}
            found += [dict(i, where="product") for i in res
                      if i["on_sale"] and matches(i["name"], rule) and i["url"] not in seen_urls]
        for i in found:
            end, et = end_text(i)
            hits.append(dict(i, store="Table Tennis 11", kind="rubber", watch=rule["label"], end=end, end_text=et))

    # 3: clothing on special <= R550
    cap = t["clothing_max_zar"]
    for i in sale_items:
        if i["on_sale"] and is_clothing(i["name"]) and to_zar(*i["special"]) <= cap:
            end, et = end_text(i)
            hits.append(dict(i, store="Table Tennis 11", kind="clothing", watch=f"Clothing ≤R{cap}", end=end, end_text=et))

    # 4: shoes on special
    shoe_items = [i for i in sale_items if is_shoe(i["name"])]
    res = tt11_page("/catalogsearch/result/?q=" + quote_plus(t["shoes_search"]))
    if res is not None:
        urls = {i["url"] for i in shoe_items}
        shoe_items += [dict(i, where="product") for i in res if is_shoe(i["name"]) and i["url"] not in urls]
    for i in shoe_items:
        if i["on_sale"]:
            end, et = end_text(i)
            hits.append(dict(i, store="Table Tennis 11", kind="shoes", watch="Shoes", end=end, end_text=et))
    return hits, ok


# ---------------------------------------------------------------- Racketlon
def rk_search_shopify(base, q):
    r = get(f"{base}/search/suggest.json", params={"q": q, "resources[type]": "product", "resources[limit]": 10})
    if not r or "json" not in r.headers.get("content-type", ""):
        return None
    out = []
    for p in r.json().get("resources", {}).get("results", {}).get("products", []):
        price = float(p.get("price") or 0)
        cmp_ = float(p.get("compare_at_price_max") or 0)
        out.append({"name": p.get("title", ""), "url": urljoin(base, p.get("url", "")),
                    "image": (p.get("featured_image") or {}).get("url", "") or p.get("image", ""),
                    "special": ("ZAR", price), "regular": ("ZAR", cmp_) if cmp_ else None,
                    "on_sale": cmp_ > price > 0, "in_stock": p.get("available", True),
                    "cats": " ".join([p.get("type", "")] + p.get("tags", []))})
    return out


def rk_search_woo(base, q):
    r = get(f"{base}/wp-json/wc/store/v1/products", params={"search": q, "per_page": 50})
    if not r or "json" not in r.headers.get("content-type", ""):
        return None
    out = []
    for p in r.json():
        pr = p.get("prices", {})
        mu = 10 ** int(pr.get("currency_minor_unit", 2))
        price = int(pr.get("price") or 0) / mu
        reg = int(pr.get("regular_price") or 0) / mu
        imgs = p.get("images") or []
        out.append({"name": BeautifulSoup(p.get("name", ""), "html.parser").get_text(), "url": p.get("permalink", ""),
                    "image": (imgs[0].get("thumbnail") or imgs[0].get("src", "")) if imgs else "",
                    "special": ("ZAR", price), "regular": ("ZAR", reg) if reg else None,
                    "on_sale": bool(p.get("on_sale")) and reg > price > 0,
                    "in_stock": p.get("is_in_stock", True),
                    "cats": " ".join(c.get("name", "") for c in p.get("categories", []))})
    return out


def rk_search_html(base, q):
    for url in (f"{base}/?s={quote_plus(q)}&post_type=product", f"{base}/search?q={quote_plus(q)}&type=product"):
        r = get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        for el in soup.select("li.product, div.product, .product-item, .grid-product, .card-wrapper, .product-card"):
            a = el.select_one("h2 a, h3 a, .woocommerce-loop-product__title, a[href*='/product']") or el.select_one("a[href]")
            name_el = el.select_one(".woocommerce-loop-product__title, h2, h3, .card__heading, .product-card__title") or a
            if not a or not name_el:
                continue
            old = el.select_one("del, s, .price--compare, .compare-at-price, .price-item--regular")
            new = el.select_one("ins, .price-item--sale, .sale-price, .price--sale")
            special = parse_money(new.get_text()) if new else None
            regular = parse_money(old.get_text()) if old else None
            im = el.select_one("img")
            out.append({"name": name_el.get_text(" ", strip=True), "url": urljoin(base, a.get("href", "")),
                        "image": urljoin(base, im.get("data-src") or im.get("src") or "") if im else "",
                        "special": special, "regular": regular,
                        "on_sale": bool(special and regular and regular[1] > special[1]),
                        "in_stock": "out of stock" not in el.get_text(" ").lower(), "cats": ""})
        if out:
            return out
    return None


_rk_method = None


def rk_search(q):
    global _rk_method
    base = CFG["racketlon"]["base"]
    methods = [("shopify", rk_search_shopify), ("woo", rk_search_woo), ("html", rk_search_html)]
    if _rk_method:
        methods = [m for m in methods if m[0] == _rk_method]
    for name, fn in methods:
        res = fn(base, q)
        if res is not None:
            if not _rk_method:
                log(f"  Racketlon: using {name} method")
            _rk_method = name
            log(f"  Racketlon '{q}': {len(res)} products, {sum(i['on_sale'] for i in res)} on special")
            return res
    return None


def is_tt(i):
    t = (i["name"] + " " + i.get("cats", "")).lower()
    return "table tennis" in t or "ping pong" in t or has_kw(i["name"], CFG["tt_brands"])


def check_racketlon():
    rk = CFG["racketlon"]
    hits, ok = [], False
    for rule in rk["rubbers"]:
        res = rk_search(rule["search"])
        if res is None:
            continue
        ok = True
        for i in res:
            if i["on_sale"] and matches(i["name"], rule):
                hits.append(dict(i, store="Racketlon", kind="rubber", watch=rule["label"], end=None, end_text="no end date listed"))
    seen = set()
    for kind, queries, test in (("clothing", rk["clothing_search"], is_clothing), ("shoes", rk["shoes_search"], is_shoe)):
        for q in queries:
            res = rk_search(q)
            if res is None:
                continue
            ok = True
            for i in res:
                if i["on_sale"] and test(i["name"]) and is_tt(i) and i["url"] not in seen:
                    seen.add(i["url"])
                    hits.append(dict(i, store="Racketlon", kind=kind, watch=kind.title(), end=None, end_text="no end date listed"))
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
           "watchlist": {"Table Tennis 11": [r["label"] for r in CFG["tt11"]["rubbers"]] + [f"Clothing ≤R{CFG['tt11']['clothing_max_zar']}", "Shoes"],
                         "Racketlon": [r["label"] for r in CFG["racketlon"]["rubbers"]] + ["Clothing", "Shoes"]}}
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
    for store, fn in (("Table Tennis 11", check_tt11), ("Racketlon", check_racketlon)):
        log(f"Checking {store}...")
        try:
            hits, ok = fn()
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
                notify(f"⚠️ Can't read {store}", f"The monitor couldn't read {store} for 3 checks in a row. "
                       "It will keep trying. Check the GitHub Actions log for details.", tags="warning")

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
