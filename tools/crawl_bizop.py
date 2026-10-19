"""Monthly-window logged-out Ad Library keyword/page sweep (active_status=all). First server-rendered page per window (top by impressions)."""
import datetime as dt, json, os, re, sys, time, pathlib
from urllib.parse import quote
from playwright.sync_api import sync_playwright
OUT = pathlib.Path("crawl"); OUT.mkdir(exist_ok=True)
def walk(o, h):
    if isinstance(o, dict):
        if "snapshot" in o and "ad_archive_id" in o: h.append(o)
        for v in o.values(): walk(v, h)
    elif isinstance(o, list):
        for v in o: walk(v, h)
def fetch(br, url):
    ctx = br.new_context(viewport={"width":1400,"height":1600}, locale="en-US")
    try:
        p = ctx.new_page(); p.goto(url, wait_until="networkidle", timeout=90000)
        t = p.inner_text("body"); m = re.search(r"~?([\d,]+) results?", t)
        rep = int(m.group(1).replace(",","")) if m else None
        hits = []
        for s in p.locator("script[type='application/json']").all():
            try: x = s.inner_text()
            except Exception: continue
            if '"ad_archive_id"' in x:
                try: walk(json.loads(x), hits)
                except Exception: pass
        if rep is None and not hits:
            if "No ads match" in t or re.search(r"\b0 results", t): return [], 0
            return None
        return hits, rep
    except Exception: return None
    finally: ctx.close()
def windows(lo, hi, days):
    d = dt.date.fromisoformat(lo); end = dt.date.fromisoformat(hi)
    while d <= end:
        e = min(d + dt.timedelta(days=days-1), end); yield d.isoformat(), e.isoformat(); d = e + dt.timedelta(days=1)
def run(job, pause):
    c = job["country"]; st = job.get("status","all")
    base = f"https://www.facebook.com/ads/library/?active_status={st}&ad_type=all&country={c}&media_type={job.get('media','all')}&sort_data[mode]=total_impressions&sort_data[direction]=desc"
    if job.get("page"): base += f"&search_type=page&view_all_page_id={job['page']}"; slug = f"{c}_page-{job['page']}" + ("_"+job["media"] if job.get("media") else "")
    else: base += f"&q={quote(job['q'])}&search_type=keyword_unordered"; slug = f"{c}_" + re.sub(r"[^a-z0-9]+","-",job["q"].lower()).strip("-") + ("_"+job["media"] if job.get("media") else "")
    seen = set(); log = []
    with sync_playwright() as pw, open(OUT/f"{slug}.jsonl","a") as f:
        br = pw.chromium.launch(); blocks = 0
        for a, z in windows(job["lo"], job["hi"], job.get("days", 30)):
            tries = 0
            while True:
                r = fetch(br, base + f"&start_date[min]={a}&start_date[max]={z}")
                if r is not None: break
                tries += 1; blocks += 1
                print("blocked", slug, a, flush=True)
                if tries >= 2 or blocks > 5: break
                time.sleep(int(os.environ.get("BACKOFF0","120")))
            if r is None:
                log.append(f"{a}..{z}: BLOCKED")
                if blocks > 5: break
                continue
            hits, rep = r; new = 0
            for h in hits:
                k = h["ad_archive_id"]
                if k not in seen:
                    seen.add(k); h["_job"] = slug; f.write(json.dumps(h, ensure_ascii=False)+"\n"); new += 1
            f.flush(); log.append(f"{a}..{z}: shown {len(hits)} reported {rep}"); print(slug, log[-1], flush=True)
            time.sleep(pause)
        br.close()
    (OUT/f"{slug}.log").write_text("\n".join(log))
if __name__ == "__main__":
    jobs = json.load(open(sys.argv[1])); run(jobs[int(sys.argv[2])], int(os.environ.get("PAUSE","6")))
