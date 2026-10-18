import sys,re,json,collections
from urllib.parse import quote
from playwright.sync_api import sync_playwright
def walk(o,hits):
    if isinstance(o,dict):
        if "snapshot" in o and "ad_archive_id" in o: hits.append(o)
        for v in o.values(): walk(v,hits)
    elif isinstance(o,list):
        for v in o: walk(v,hits)
import os
items=json.loads(sys.argv[1]); os.makedirs("crawl",exist_ok=True); out=[]
with sync_playwright() as pw:
    b=pw.chromium.launch()
    for country,q in items:
        ctx=b.new_context(viewport={"width":1400,"height":1600},locale="en-US");p=ctx.new_page()
        url=f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country={country}&media_type=all&q={quote(q)}&search_type=keyword_unordered&sort_data[mode]=total_impressions&sort_data[direction]=desc"
        try:
            p.goto(url,wait_until="domcontentloaded",timeout=60000); p.wait_for_timeout(9000); p.wait_for_timeout(3000); print(len(p.content()), p.inner_text("body")[:200].replace(chr(10)," "))
            hits=[]
            for s in p.locator("script[type='application/json']").all():
                try:t=s.inner_text()
                except: continue
                if '"ad_archive_id"' in t:
                    try: walk(json.loads(t),hits)
                    except: pass
            c=collections.Counter((h["page_id"],h["snapshot"].get("page_name")) for h in hits)
            print("Q:",country,q,len(hits),dict(c.most_common(15)),flush=True); out.append({"country":country,"q":q,"pages":[[k[0],k[1],v] for k,v in c.most_common(25)]})
        except Exception as e: print("Q:",q,"ERR",str(e)[:80],flush=True)
        ctx.close()
    b.close()
json.dump(out,open("crawl/disc_"+sys.argv[2]+".json","w"))
