# TT Deals 🏓

A small app that watches table tennis shops for specials on my gear and alerts my phone.

**Shops:** Table Tennis 11 (Estonia), Racketlon (South Africa), Megaspin (USA), Dandoy Sports (Belgium), Butterfly US, JOOLA US, JOOLA Europe, Donic (Germany), STIGA (Sweden).

**App:** https://yashiljaimungal4.github.io/tt-specials/

## How it works
- GitHub Actions runs `monitor.py` 5 times a day (07:07, 12:07, 13:37, 16:07, 20:07 SA time).
- It reads each store's specials, keeps only the watchlist items, converts euro prices to rand, and writes `docs/deals.json`.
- The app (`docs/`) shows those deals as cards, with a live countdown for Table Tennis 11 weekly specials (new ones every Monday, ending Sunday midnight).
- New specials trigger a notification on every phone connected through the app's bell button. It alerts once per special, plus a "last day" reminder on Sundays.

## What it covers
Every table tennis special at those shops, sorted into rubbers, blades, rackets, balls, clothing, shoes, bags, accessories, robots and tables (sorting is automatic and occasionally wrong).

Anyone can browse and filter the deals (price, % off, shop, search, sort); filters are saved on their own phone.

## Alerts
`alert_prefs.json` decides what alerts the owner's phone: watched items (always), plus each category on/off with a max rand price and minimum % off, and which shops. Change it from the app (bell > Alert settings > Save) or edit the file.
Built-in watched items are in `config.json` (`watchlist.rubbers`).
`monitor_end_date` in `config.json` stops checking after that date (currently 31 Jan 2027).

## Setup notes
- Secret `VAPID_PRIVATE_KEY` (Settings → Secrets and variables → Actions) signs the notifications.
- Settings → Pages → Source: **GitHub Actions**.
- To connect a phone: open the app → bell → **Allow notifications** → submit the GitHub issue it opens.
- Manual run: Actions → *Check table tennis specials* → Run workflow (`normal`, `dry-run`, `test-alert`).
