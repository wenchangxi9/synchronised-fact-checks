"""Rebuild the audited display mapping used by package_github_data.py."""
import sqlite3,json
from pathlib import Path
base=Path('outputs/media_note_posts');out=base/'extended_observation'
c=sqlite3.connect(base/'display_repair/display_evidence.sqlite')
mapping=dict(c.execute("select postId,noteId from evidence where evidenceLevel='verified_media_note_cross_post'"))
for row in json.loads((out/'additional_cached_display.json').read_text()):
    if row['verifiedMediaNote']:mapping[row['postId']]=row['noteId']
r=sqlite3.connect('outputs/reuse.sqlite')
origin=dict(r.execute('select noteId,tweetId from notes where media=1'))
e=sqlite3.connect(out/'extended.sqlite')
for pid,nid in e.execute("select postId,pivotNoteId from fetched where valid=1 and lower(pivotTitle) like '%another post%'"):
    if nid in origin and origin[nid]!=pid:mapping[pid]=nid
(out/'verified_display_union.json').write_text(json.dumps(mapping),encoding='utf-8')
rechecks=json.loads((base/'display_repair/failed_post_rechecks.json').read_text())
(base/'display_repair/recovered_posts.json').write_text(json.dumps([x for x in rechecks if x.get('valid')],indent=2),encoding='utf-8')
print('verified posts',len(mapping),'notes',len(set(mapping.values())))
