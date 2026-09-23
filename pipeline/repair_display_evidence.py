import sqlite3,json,random,collections,datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import requests

out=Path('outputs/media_note_posts/display_repair');out.mkdir(exist_ok=True)
c=sqlite3.connect('outputs/media_note_posts/media_note_posts.sqlite')
c.execute("attach database 'outputs/reuse.sqlite' as r")
candidate_ids={r[0] for r in c.execute("select distinct postId from note_post_links where relationship='matched_rating_context'")}
rows=c.execute('''select p.postId,p.pivotNoteId,p.pivotTitle,p.confirmedMediaMatchedShown,
 n.media,n.tweetId,p.retrievedUtc,
 0
 from post_info p left join r.notes n on n.noteId=p.pivotNoteId
 where lower(p.pivotTitle) like '%another post%' ''').fetchall()
db=sqlite3.connect(out/'display_evidence.sqlite')
db.execute('''create table if not exists evidence(postId text primary key,noteId text,title text,
 legacyConfirmed integer,isMediaNote integer,noteOriginalPostId text,retrievedUtc text,
 inCandidateTargetSet integer,evidenceLevel text)''')
for row in rows:
 row=(*row[:7],int(row[0] in candidate_ids))
 level='verified_media_note_cross_post' if row[4]==1 and row[5]!=row[0] else 'display_metadata_note_absent_from_cutoff'
 db.execute('insert or replace into evidence values(?,?,?,?,?,?,?,?,?)',(*row,level))
db.commit()
summary={}
for scope,where in [('candidate_targets','inCandidateTargetSet=1'),('all_collected_posts','1=1')]:
 summary[scope]=[dict(zip(['level','posts','notes'],r)) for r in db.execute(f'select evidenceLevel,count(*),count(distinct noteId) from evidence where {where} group by evidenceLevel')]
summary['candidate_extra_posts']=[dict(zip(['level','posts','notes'],r)) for r in db.execute("select evidenceLevel,count(*),count(distinct noteId) from evidence where inCandidateTargetSet=1 and legacyConfirmed=0 group by evidenceLevel")]
summary['new_note_ids_verified_candidates']=db.execute('''select count(distinct noteId) from evidence where inCandidateTargetSet=1 and evidenceLevel='verified_media_note_cross_post' and noteId not in (select noteId from evidence where legacyConfirmed=1)''').fetchone()[0]
(out/'evidence_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary),flush=True)
failed=c.execute('''select distinct p.postId,p.fetchStatus,p.httpStatus from post_payloads p join note_post_links l on l.postId=p.postId where l.relationship='matched_rating_context' and p.fetchStatus!='ok' ''').fetchall()
rng=random.Random(20260923)
sample=[r for r in failed if r[1]!='unavailable']+rng.sample([r for r in failed if r[1]=='unavailable'],200)
def fetch(row):
 pid,old,status=row;r={'postId':pid,'oldStatus':old,'oldHttp':status,'retrievedUtc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 try:
  q=requests.get('https://cdn.syndication.twimg.com/tweet-result',params={'id':pid,'lang':'en','token':'0'},headers={'User-Agent':'Mozilla/5.0','Cache-Control':'no-cache'},timeout=20)
  r['http']=q.status_code
  (out/(pid+'.json')).write_text(q.text,encoding='utf-8')
  try:o=q.json()
  except ValueError:o={}
  r['valid']=str(o.get('id_str'))==pid and isinstance(o.get('text'),str)
  r['pivot']=o.get('birdwatch_pivot')
 except Exception as e:r['error']=str(e)
 return r
with ThreadPoolExecutor(max_workers=16) as pool:results=list(pool.map(fetch,sample))
(out/'failed_post_rechecks.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
print('RETRIES',collections.Counter((r['oldStatus'],r.get('http'),r.get('valid')) for r in results),flush=True)
