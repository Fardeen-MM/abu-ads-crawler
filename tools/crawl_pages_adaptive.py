"""Adaptive page pull (active_status=all): fetch a page's whole date range; halve any window that returns >=28 ads or fewer than reported."""
import datetime as dt, json, os, sys, time, pathlib
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(__file__))
from crawl_bizop import fetch, OUT
def pull(br, pid, lo, hi, pause):
    base = f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=ALL&media_type=all&sort_data[mode]=total_impressions&sort_data[direction]=desc&search_type=page&view_all_page_id={pid}"
    q = [(lo, hi)]; seen = {}; blocks = 0; loads = 0
    while q and loads < 120:
        a, z = q.pop(0); r = None
        for t in range(2):
            r = fetch(br, base + f"&start_date[min]={a}&start_date[max]={z}"); loads += 1
            if r is not None: break
            blocks += 1; time.sleep(int(os.environ.get("BACKOFF0", "120")))
        if r is None:
            if blocks > 6: break
            continue
        hits, rep = r
        for h in hits: seen.setdefault(h["ad_archive_id"], h)
        da, dz = dt.date.fromisoformat(a), dt.date.fromisoformat(z)
        if (len(hits) >= 28 or (rep and rep > len(hits))) and (dz - da).days >= 1:
            mid = da + (dz - da) // 2
            q[:0] = [(a, mid.isoformat()), ((mid + dt.timedelta(days=1)).isoformat(), z)]
        print(pid, a, z, len(hits), rep, flush=True); time.sleep(pause)
    with open(OUT / f"ALL_page-{pid}.jsonl", "w") as f:
        for h in seen.values(): h["_job"] = f"page-{pid}"; f.write(json.dumps(h, ensure_ascii=False) + "\n")
if __name__ == "__main__":
    job = json.load(open(sys.argv[1]))[int(sys.argv[2])]
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for pid in job["pages"]: pull(br, pid, job.get("lo", "2022-01-01"), job.get("hi", "2026-10-18"), int(os.environ.get("PAUSE", "5")))
        br.close()
