# TT Deals 🏓

A small app that watches **Table Tennis 11** and **Racketlon Sports** for specials on my gear and alerts my phone.

**App:** https://yashiljaimungal4.github.io/tt-specials/

## How it works
- GitHub Actions runs `monitor.py` 5 times a day (07:07, 12:07, 13:37, 16:07, 20:07 SA time).
- It reads each store's specials, keeps only the watchlist items, converts euro prices to rand, and writes `docs/deals.json`.
- The app (`docs/`) shows those deals as cards, with a live countdown for Table Tennis 11 weekly specials (new ones every Monday, ending Sunday midnight).
- New specials trigger a notification on every phone connected through the app's bell button. It alerts once per special, plus a "last day" reminder on Sundays.

## Watchlist
Edit `config.json`:
- **Table Tennis 11:** Donic Bluestar A1, Andro Nuzn 55, clothing on special up to R550, shoes on special
- **Racketlon:** Butterfly Dignics, Tenergy 05 / 05 Hard, table tennis clothing and shoes on special
- `monitor_end_date`: the app stops checking after this date (currently 31 Jan 2027)

## Setup notes
- Secret `VAPID_PRIVATE_KEY` (Settings → Secrets and variables → Actions) signs the notifications.
- Settings → Pages → Source: **GitHub Actions**.
- To connect a phone: open the app → bell → **Allow notifications** → submit the GitHub issue it opens.
- Manual run: Actions → *Check table tennis specials* → Run workflow (`normal`, `dry-run`, `test-alert`).
