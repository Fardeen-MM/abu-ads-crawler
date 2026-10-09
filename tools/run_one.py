"""Run one crawl job (by index into jobs.json) on a CI runner; results land in crawl/."""
import json, sys, pathlib, os
sys.path.insert(0, os.path.dirname(__file__))
import crawl
i = int(sys.argv[1])
job = json.load(open("jobs.json"))[i]
pathlib.Path("one.json").write_text(json.dumps([job]))
crawl.PAUSE = int(os.environ.get("PAUSE", "20"))
crawl.run("one.json")
