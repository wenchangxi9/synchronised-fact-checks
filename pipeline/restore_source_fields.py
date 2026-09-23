import sqlite3,gzip,json,zipfile,tarfile,io,hashlib,csv
from pathlib import Path
root=Path('data/media_matching_2026_09_23');raw=root/'source_records';raw.mkdir(exist_ok=True)
derived=root/'derived';derived.mkdir(exist_ok=True)
for p in list(root.glob('*.gz'))+list(root.glob('manifest.json')):
 if (derived/p.name).exists():raise FileExistsError(derived/p.name)
 p.rename(derived/p.name)
c=sqlite3.connect('outputs/media_note_posts/media_note_posts.sqlite')
ids={n for n, in c.execute('select noteId from media_notes')}
src=Path('source/raw_snapshot')
manifest={}
for pattern,name in [('notes-*.zip','notes.tsv.gz'),('noteStatusHistory-*.zip','noteStatusHistory.tsv.gz')]:
 count=0;header=None
 with gzip.open(raw/name,'wb') as out:
  for p in sorted(src.glob(pattern)):
   with zipfile.ZipFile(p) as z:
    with z.open(z.namelist()[0]) as f:
     h=f.readline()
     if header is None:header=h;out.write(h)
     else:assert h==header
     for line in f:
      if line.split(b'\t',1)[0].decode() in ids:out.write(line);count+=1
 manifest[name]={'rows':count};print(name,count,flush=True)
seen=set();part=0;archive=None;partcount=0
def add(pid,payload):
 global part,archive,partcount
 if pid in seen:return
 if archive is None or partcount>=10000:
  if archive:archive.close()
  part+=1;partcount=0;name=f'posts-{part:03}.tar.gz';archive=tarfile.open(raw/name,'w:gz');manifest[name]={'records':0}
 info=tarfile.TarInfo(pid+'.json');info.size=len(payload);info.mtime=0
 archive.addfile(info,io.BytesIO(payload));seen.add(pid);partcount+=1;manifest[f'posts-{part:03}.tar.gz']['records']+=1
for pid,blob in c.execute("select postId,payloadGzip from post_payloads where fetchStatus='ok'"):add(pid,gzip.decompress(blob))
old=sqlite3.connect('outputs/post_similarity/full_collection/full_posts.sqlite')
for x in json.loads(Path('outputs/media_note_posts/extended_observation/additional_cached_display.json').read_text()):
 if x['verifiedMediaNote']:
  blob=old.execute('select payload_gzip from posts where post_id=?',(x['postId'],)).fetchone()[0];add(x['postId'],gzip.decompress(blob))
e=sqlite3.connect('outputs/media_note_posts/extended_observation/extended.sqlite')
for pid,blob in e.execute('select postId,payload from fetched where valid=1'):add(pid,gzip.decompress(blob))
for x in json.loads(Path('outputs/media_note_posts/display_repair/recovered_posts.json').read_text()):add(x['postId'],Path('outputs/media_note_posts/display_repair',x['postId']+'.json').read_bytes())
if archive:archive.close()
for name,info in manifest.items():
 p=raw/name;info['bytes']=p.stat().st_size;info['sha256']=hashlib.sha256(p.read_bytes()).hexdigest();assert p.stat().st_size<95*1024**2
(raw/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print('raw posts',len(seen),'parts',part,flush=True)
