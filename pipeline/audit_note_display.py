import sqlite3,json,gzip,random,collections,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import requests

out=Path('outputs/media_note_posts/display_audit');out.mkdir(exist_ok=True)
c=sqlite3.connect('outputs/media_note_posts/media_note_posts.sqlite')
links=collections.defaultdict(set)
for n,p in c.execute("select noteId,postId from note_post_links where relationship='matched_rating_context'"):links[p].add(n)
counts=collections.Counter();titles=collections.Counter();mismatches=[];groups=collections.defaultdict(list)
for pid,blob,stored,stored_id in c.execute('select p.postId,r.payloadGzip,p.confirmedMediaMatchedShown,p.pivotNoteId from post_info p join post_payloads r using(postId)'):
 if pid not in links:continue
 counts['target_payloads']+=1
 try:o=json.loads(gzip.decompress(blob))
 except Exception as e:mismatches.append([pid,'decode',str(e)]);continue
 pv=o.get('birdwatch_pivot') or {};nid=str(pv.get('noteId') or '')
 title=str(pv.get('title') or '')
 calculated=int(nid in links[pid] and 'another post' in title.lower())
 if calculated!=stored or nid!=(stored_id or ''):mismatches.append([pid,'stored_diff',nid,stored_id])
 if str(o.get('id_str'))!=pid:counts['id_mismatch']+=1
 if pv:titles[title]+=1
 category='confirmed' if calculated else ('no_pivot' if not pv else 'other_pivot')
 counts[category]+=1;groups[category].append({'postId':pid,'oldNoteId':nid,'oldTitle':title,'category':category})
 # Inspect alternate top-level metadata keys to detect schema changes.
 for k in o:
  if any(s in k.lower() for s in ['birdwatch','note','context']):counts['key:'+k]+=1
audit={'counts':dict(counts),'titles':dict(titles),'parser_mismatches':mismatches}
(out/'full_payload_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
random.seed(20260922)
sample=[]
for cat,rows in groups.items():sample+=random.sample(rows,min(100,len(rows)))
(out/'sample.json').write_text(json.dumps(sample,indent=2),encoding='utf-8')
print('AUDIT',json.dumps(audit),flush=True)
def fetch(r):
 result=dict(r)
 try:
  q=requests.get('https://cdn.syndication.twimg.com/tweet-result',params={'id':r['postId'],'lang':'en','token':'0'},timeout=25)
  result['httpStatus']=q.status_code
  (out/(r['postId']+'.json')).write_text(q.text,encoding='utf-8')
  o=q.json();pv=o.get('birdwatch_pivot') or {};nid=str(pv.get('noteId') or '')
  result['validPost']=str(o.get('id_str'))==r['postId']
  result['newNoteId']=nid;result['newTitle']=pv.get('title')
  result['newCategory']='unavailable' if not result['validPost'] else ('confirmed' if nid in links[r['postId']] and 'another post' in str(pv.get('title','')).lower() else ('no_pivot' if not pv else 'other_pivot'))
 except Exception as e:result['newCategory']='error';result['error']=str(e)
 return result
with ThreadPoolExecutor(max_workers=12) as pool:results=list(pool.map(fetch,sample))
(out/'recheck_results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
transition=collections.Counter((r['category'],r['newCategory']) for r in results)
print('TRANSITIONS',list(transition.items()),flush=True)
