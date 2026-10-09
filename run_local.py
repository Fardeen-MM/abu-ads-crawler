import sys, os
sys.path.insert(0, 'tools'); import crawl
crawl.PAUSE = int(os.environ.get('PAUSE', '15'))
crawl.run('local_jobs.json')
