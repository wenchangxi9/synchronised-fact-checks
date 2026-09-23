import sqlite3,zipfile,json,time,gzip,datetime,threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pyarrow as pa
import pyarrow.csv as csv
import pyarrow.compute as pc
import requests

out=Path('outputs/media_note_posts/extended_observation');out.mkdir(exist_ok=True)
db=sqlite3.connect(out/'extended.sqlite')
db.executescript('''CREATE TABLE IF NOT EXISTS links(noteId TEXT,postId TEXT,firstMs INTEGER,PRIMARY KEY(noteId,postId));
CREATE TABLE IF NOT EXISTS done(file TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS fetched(postId TEXT PRIMARY KEY,http INTEGER,valid INTEGER,pivotNoteId TEXT,pivotTitle TEXT,retrievedUtc TEXT,payload BLOB,error TEXT);''')
base=sqlite3.connect('outputs/media_note_posts/media_note_posts.sqlite')
known={(n,p) for n,p in base.execute("select noteId,postId from note_post_links where relationship='matched_rating_context'")}
oldids={p for _,p in known}
reuse=sqlite3.connect('outputs/reuse.sqlite')
orig=dict(reuse.execute('select noteId,tweetId from notes where media=1'))
vals=pa.array(list(orig),type=pa.string())
source=Path('source/raw_snapshot')
opts=csv.ConvertOptions(include_columns=['noteId','ratedOnTweetId','createdAtMillis'],column_types={'noteId':pa.string(),'ratedOnTweetId':pa.string(),'createdAtMillis':pa.int64()})
for path in sorted(source.glob('ratings-*.zip'),reverse=True):
 if db.execute('select 1 from done where file=?',(path.name,)).fetchone():continue
 t=time.time();scanned=0
 with zipfile.ZipFile(path) as z:
  with z.open(z.namelist()[0]) as f:
   reader=csv.open_csv(f,read_options=csv.ReadOptions(block_size=32*1024*1024),parse_options=csv.ParseOptions(delimiter='\t'),convert_options=opts)
   for b in reader:
    scanned+=b.num_rows
    s=b.filter(pc.is_in(b.column('noteId'),value_set=vals)).to_pydict()
    rows=[(n,p,t) for n,p,t in zip(s['noteId'],s['ratedOnTweetId'],s['createdAtMillis']) if p and p not in ('0','-1',orig[n]) and (n,p) not in known]
    db.executemany('insert into links values(?,?,?) on conflict(noteId,postId) do update set firstMs=min(firstMs,excluded.firstMs)',rows)
 db.execute('insert into done values(?)',(path.name,));db.commit()
 print(json.dumps({'file':path.name,'rows':scanned,'seconds':round(time.time()-t),'additional_pairs':db.execute('select count(*) from links').fetchone()[0]}),flush=True)

extraids={p for p, in db.execute('select distinct postId from links')}
summary={'original_media_note_cohort':len(orig),'additional_associations':db.execute('select count(*) from links').fetchone()[0],'notes_with_additional_associations':db.execute('select count(distinct noteId) from links').fetchone()[0],'new_candidate_posts':len(extraids-oldids),'union_candidate_posts':len(extraids|oldids),'union_notes_with_candidates':len({n for n,_ in known}|{n for n, in db.execute('select distinct noteId from links')})}
(out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary),flush=True)
# Fetch only newly discovered post IDs not already successfully collected.
success={p for p, in base.execute("select postId from post_payloads where fetchStatus='ok'")}
done={p for p, in db.execute('select postId from fetched')}
todo=sorted(extraids-oldids-success-done)
local=threading.local()
def fetch(pid):
 if not hasattr(local,'s'):local.s=requests.Session()
 stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
 try:
  q=local.s.get('https://cdn.syndication.twimg.com/tweet-result',params={'id':pid,'lang':'en','token':'0'},timeout=15)
  try:o=q.json()
  except ValueError:o={}
  valid=isinstance(o,dict) and str(o.get('id_str'))==pid and isinstance(o.get('text'),str)
  pivot=(o.get('birdwatch_pivot') or {}) if isinstance(o,dict) else {}
  return(pid,q.status_code,int(valid),str(pivot.get('noteId','')),pivot.get('title',''),stamp,gzip.compress(q.content),None)
 except Exception as e:return(pid,None,0,None,None,stamp,None,str(e))
print('NEW POSTS TO FETCH',len(todo),flush=True)
with ThreadPoolExecutor(max_workers=12) as pool:
 for i,row in enumerate(pool.map(fetch,todo),1):
  db.execute('insert or replace into fetched values(?,?,?,?,?,?,?,?)',row)
  if i%100==0:db.commit();print('fetched',i,'of',len(todo),flush=True)
db.commit()
summary['fetched_status_counts']=db.execute('select http,valid,count(*) from fetched group by http,valid').fetchall()
summary['crosspost_metadata_posts']=db.execute("select count(*) from fetched where valid=1 and lower(pivotTitle) like '%another post%'").fetchone()[0]
(out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary),flush=True)
