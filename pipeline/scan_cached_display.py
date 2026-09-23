import sqlite3,gzip,json
from pathlib import Path
out=Path('outputs/media_note_posts/extended_observation')
c=sqlite3.connect('outputs/post_similarity/full_collection/full_posts.sqlite')
b=sqlite3.connect('outputs/media_note_posts/media_note_posts.sqlite')
known={r[0] for r in b.execute('select postId from post_info')}
r=sqlite3.connect('outputs/reuse.sqlite')
notes=dict(r.execute('select noteId,tweetId from notes where media=1'))
found=[];scanned=0
for pid,stamp,raw in c.execute("select post_id,retrieved_utc,payload_gzip from posts where fetch_status='ok'"):
 if pid in known:continue
 scanned+=1
 try:o=json.loads(gzip.decompress(raw))
 except Exception:continue
 p=o.get('birdwatch_pivot') or {};nid=str(p.get('noteId',''));title=p.get('title','')
 if 'another post' in title.lower():
  found.append({'postId':pid,'noteId':nid,'title':title,'retrievedUtc':stamp,'verifiedMediaNote':nid in notes and notes[nid]!=pid})
(out/'additional_cached_display.json').write_text(json.dumps(found,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'previously_unincluded_cached_posts':scanned,'crosspost_metadata':len(found),'verified_media_crosspost':sum(x['verifiedMediaNote'] for x in found),'notes':len({x['noteId'] for x in found if x['verifiedMediaNote']})}))
