"""Patient, logged-out Ad Library crawler. No Facebook account is ever used.

Every page load is a fresh incognito browser context (no cookies). Only the first, server-rendered
page of results is read (logged-out pagination is rate-limited). Coverage comes from date slicing:
a window that comes back full is split in half until every window is under-full; a single full day
is split further by media type, then platform.

Blocking is never skipped: a blank / rate-limited load waits (10 min, growing) and retries the SAME
window. Progress is saved after every load (crawl/state.json), so the job can be killed and resumed.

Each search records Facebook's own "~N results" total so coverage can be checked: collected vs reported.

usage:  python3 crawl.py jobs.json        (jobs: [{"country":"US","q":"free masterclass","lo":"2018-01-01","hi":"2026-04-30"},
                                                  {"country":"ALL","page":"293210107207936","lo":...,"hi":...}])
"""
import datetime as dt, json, os, re, sys, time, pathlib
from urllib.parse import quote
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent / "crawl"
FULL = 28
PAUSE = 45
BASE = ("https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country={c}&media_type=all"
        "&sort_data[mode]=total_impressions&sort_data[direction]=desc")


def walk(o, hits):
    if isinstance(o, dict):
        if "snapshot" in o and "ad_archive_id" in o:
            hits.append(o)
        for v in o.values():
            walk(v, hits)
    elif isinstance(o, list):
        for v in o:
            walk(v, hits)


def fetch(browser, url):
    """One incognito load. Returns (hits, reported_total) or None when Facebook served a blank/blocked page."""
    ctx = browser.new_context(viewport={"width": 1400, "height": 1600}, locale="en-US")
    try:
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle", timeout=90000)
        text = page.inner_text("body")
        m = re.search(r"~?([\d,]+) results?", text)
        reported = int(m.group(1).replace(",", "")) if m else None
        hits = []
        for s in page.locator("script[type='application/json']").all():
            try:
                t = s.inner_text()
            except Exception:
                continue
            if '"ad_archive_id"' in t:
                try:
                    walk(json.loads(t), hits)
                except Exception:
                    pass
        if reported is None and not hits:
            # A genuinely empty search still prints "0 results"; no count at all = blocked page.
            if "No ads match" in text or re.search(r"\b0 results", text):
                return ([], 0)
            return None
        return hits, reported
    except Exception:
        return None
    finally:
        ctx.close()


def job_base(j):
    b = BASE.replace("{c}", j["country"])
    if j.get("page"):
        return b + f"&search_type=page&view_all_page_id={j['page']}", f"{j['country']}_page-{j['page']}"
    return (b + f"&q={quote(j['q'])}&search_type=keyword_unordered",
            f"{j['country']}_" + re.sub(r"[^a-z0-9]+", "-", j["q"].lower()).strip("-"))


def run(jobs_file):
    ROOT.mkdir(exist_ok=True)
    jobs = json.load(open(jobs_file))
    state_f = ROOT / "state.json"
    state = json.load(open(state_f)) if state_f.exists() else {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for j in jobs:
            base, slug = job_base(j)
            st = state.setdefault(slug, {"queue": [[base, j["lo"], j["hi"]]], "done": 0, "reported": None,
                                         "finished": False, "saturated": []})
            if st["finished"]:
                continue
            out_f = ROOT / f"{slug}.jsonl"
            seen = set()
            if out_f.exists():
                seen = {json.loads(l)["ad_archive_id"] for l in open(out_f)}
            backoff = int(os.environ.get("BACKOFF0", "900")); blocks = 0
            while st["queue"]:
                b, a, z = st["queue"][0]
                url = b + f"&start_date[min]={a}&start_date[max]={z}"
                res = fetch(browser, url)
                if res is None:
                    print(time.strftime("%H:%M"), slug, f"blocked on {a}..{z}; waiting {backoff // 60} min", flush=True)
                    blocks += 1
                    if blocks > int(os.environ.get("MAX_BLOCKS", "999")):
                        print("giving up on this runner (still blocked)", flush=True); break
                    time.sleep(backoff); backoff = min(backoff * 2, 3600)
                    continue
                backoff = int(os.environ.get("BACKOFF0", "900")); blocks = 0
                hits, reported = res
                st["queue"].pop(0); st["done"] += 1
                if st["reported"] is None and a == j["lo"] and z == j["hi"] and "media_type=all" in b:
                    st["reported"] = reported
                new = 0
                with open(out_f, "a") as f:
                    for h in hits:
                        if h["ad_archive_id"] not in seen:
                            seen.add(h["ad_archive_id"]); new += 1
                            h["_job"] = slug
                            f.write(json.dumps(h, ensure_ascii=False) + "\n")
                da, dz = dt.date.fromisoformat(a), dt.date.fromisoformat(z)
                more = (reported is not None and reported > len(hits)) or len(hits) >= FULL
                if more and (dz - da).days >= 1:
                    mid = da + (dz - da) // 2
                    st["queue"][:0] = [[b, a, mid.isoformat()], [b, (mid + dt.timedelta(days=1)).isoformat(), z]]
                elif more and "media_type=all" in b:
                    st["queue"][:0] = [[b.replace("media_type=all", f"media_type={m}"), a, z] for m in ("image", "video", "meme", "none")]
                elif more and "publisher_platforms" not in b:
                    st["queue"][:0] = [[b + f"&publisher_platforms[0]={p}", a, z] for p in ("facebook", "instagram", "audience_network", "messenger")]
                elif more:
                    st["saturated"].append([a, b[-80:]])
                print(time.strftime("%H:%M"), slug, f"{a}..{z}: {len(hits)} (+{new}) total {len(seen)} / reported {st['reported']}",
                      f"queue {len(st['queue'])}", flush=True)
                json.dump(state, open(state_f, "w"))
                time.sleep(PAUSE)
            st["finished"] = True
            st["collected"] = len(seen)
            json.dump(state, open(state_f, "w"))
            print(time.strftime("%H:%M"), "DONE", slug, "collected", len(seen), "reported", st["reported"],
                  "saturated", len(st["saturated"]), flush=True)
        browser.close()


if __name__ == "__main__":
    run(sys.argv[1])
