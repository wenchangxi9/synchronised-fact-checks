"""Verify published files and joins without network or private source databases."""
import csv,gzip,json,hashlib
from pathlib import Path

root=Path(__file__).resolve().parents[1]/'data/media_matching_2026_09_23'
manifest=json.loads((root/'manifest.json').read_text())
for name,meta in manifest.items():
    path=root/name
    assert hashlib.sha256(path.read_bytes()).hexdigest()==meta['sha256'],name
    with gzip.open(path,'rt',encoding='utf-8',newline='') as f:
        count=sum(1 for _ in f) if '.jsonl.' in name else sum(1 for _ in csv.DictReader(f))
    assert count==meta['rows'],(name,count)
def rows(name):
    with gzip.open(root/name,'rt',encoding='utf-8',newline='') as f:
        yield from csv.DictReader(f)
notes={x['noteId'] for x in rows('media_notes.csv.gz')}
posts={x['postId'] for x in rows('posts.csv.gz')}
with gzip.open(root/'supplemental_posts.jsonl.gz','rt',encoding='utf-8') as f:
    posts.update(json.loads(line)['postId'] for line in f)
display=list(rows('verified_display.csv.gz'))
assert len({x['postId'] for x in display})==len(display)
assert all(x['noteId'] in notes and x['postId'] in posts for x in display)
print(json.dumps({'verified_files':len(manifest),'media_notes':len(notes),'available_posts':len(posts),'display_posts':len(display),'display_notes':len({x['noteId'] for x in display}),'missing_display_joins':0},indent=2))
