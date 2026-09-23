"""Validate raw archive integrity, original ID fields and release coverage."""
import csv,gzip,hashlib,json,tarfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'data/media_matching_2026_09_23'
raw=root/'source_records';manifest=json.loads((raw/'manifest.json').read_text())
for name,meta in manifest.items():
    assert hashlib.sha256((raw/name).read_bytes()).hexdigest()==meta['sha256'],name
with gzip.open(raw/'notes.tsv.gz','rt',encoding='utf-8',newline='') as f:
    reader=csv.DictReader(f,delimiter='\t');assert 'tweetId' in reader.fieldnames and 'originalPostId' not in reader.fieldnames
    notes={r['noteId'] for r in reader}
posts=set()
for file in sorted(raw.glob('posts-*.tar.gz')):
    count=0
    with tarfile.open(file) as archive:
        for member in archive:
            obj=json.load(archive.extractfile(member));pid=member.name.removesuffix('.json')
            assert obj['id_str']==pid and pid not in posts
            posts.add(pid);count+=1
    assert count==manifest[file.name]['records']
with gzip.open(root/'derived/verified_display.csv.gz','rt',encoding='utf-8',newline='') as f:
    for row in csv.DictReader(f):assert row['noteId'] in notes and row['postId'] in posts
print(json.dumps({'source_notes':len(notes),'source_posts':len(posts),'display_joins':'all present'}))
