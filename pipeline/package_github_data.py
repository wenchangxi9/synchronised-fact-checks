import sqlite3,csv,gzip,json,hashlib,shutil
from pathlib import Path
root=Path('data/media_matching_2026_09_23');root.mkdir(parents=True,exist_ok=True)
base=Path('outputs/media_note_posts'); manifest={}
def export(db,name,sql):
 cur=db.execute(sql);n=0
 with gzip.open(root/name,'wt',encoding='utf-8',newline='') as f:
  w=csv.writer(f);w.writerow([x[0] for x in cur.description])
  for row in cur:w.writerow(row);n+=1
 manifest[name]={'rows':n}
c=sqlite3.connect(base/'media_note_posts.sqlite')
export(c,'media_notes.csv.gz','select noteId,noteAuthorId,noteCreatedAtMs,originalPostId,classification,currentStatus,firstStatusAtMs,stableHelpfulStartMs,noteText,isAiAuthor AS isCollaborativeNote from media_notes')
export(c,'links_cutoff.csv.gz','select * from note_post_links')
export(c,'posts.csv.gz','select * from post_info')
export(c,'fetch_log.csv.gz','select postId,fetchStatus,httpStatus,retrievedUtc,attempts,lastError from post_payloads')
e=sqlite3.connect(base/'extended_observation/extended.sqlite')
export(e,'links_extended.csv.gz','select noteId,postId,firstMs as firstObservedRatingMs from links')
mapping=json.loads((base/'extended_observation/verified_display_union.json').read_text())
with gzip.open(root/'verified_display.csv.gz','wt',encoding='utf-8',newline='') as f:
 w=csv.writer(f);w.writerow(['postId','noteId']);w.writerows(mapping.items())
manifest['verified_display.csv.gz']={'rows':len(mapping)}
existing={p for p, in c.execute('select postId from post_info')};supp={}
cache=json.loads((base/'extended_observation/additional_cached_display.json').read_text())
old=sqlite3.connect('outputs/post_similarity/full_collection/full_posts.sqlite')
for x in cache:
 if x['verifiedMediaNote']:
  row=old.execute('select retrieved_utc,payload_gzip from posts where post_id=?',(x['postId'],)).fetchone()
  supp[x['postId']]={'postId':x['postId'],'retrievedUtc':row[0],'payload':json.loads(gzip.decompress(row[1]))}
for pid,stamp,raw in e.execute('select postId,retrievedUtc,payload from fetched where valid=1'):
 supp[pid]={'postId':pid,'retrievedUtc':stamp,'payload':json.loads(gzip.decompress(raw))}
for x in json.loads((base/'display_repair/recovered_posts.json').read_text()):
 supp[x['postId']]={'postId':x['postId'],'retrievedUtc':x['retrievedUtc'],'payload':json.loads((base/'display_repair'/ (x['postId']+'.json')).read_text())}
with gzip.open(root/'supplemental_posts.jsonl.gz','wt',encoding='utf-8') as f:
 for x in supp.values():f.write(json.dumps(x,ensure_ascii=False)+'\n')
manifest['supplemental_posts.jsonl.gz']={'rows':len(supp)}
assert set(mapping)<=existing|set(supp)
assert set(mapping.values())<={n for n, in c.execute('select noteId from media_notes')}
for name in manifest:
 p=root/name;manifest[name].update(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
 assert p.stat().st_size<95*1024**2
(root/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(json.dumps(manifest,indent=2))
