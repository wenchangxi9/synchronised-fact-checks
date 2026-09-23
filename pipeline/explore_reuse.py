"""Read-only analysis of CN cutoff archive; all outputs stay in this workspace."""
from pathlib import Path
import sqlite3, csv, io, zipfile, re, hashlib, json, time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs'
OUT.mkdir(exist_ok=True)
SOURCE = Path('source/cutoff_zip')
CUTOFF = 1785110399999
db = sqlite3.connect(OUT / 'reuse.sqlite')
db.execute('PRAGMA journal_mode=WAL')
db.execute('PRAGMA synchronous=NORMAL')
db.execute('PRAGMA cache_size=-48000')
db.execute('PRAGMA temp_store=FILE')
URL = re.compile(r'https?://\S+|www\.\S+', re.I)
def norm(s): return ' '.join(s.casefold().split())
def digest(s): return hashlib.sha256(s.encode()).digest() if s else None
def integer(s):
    try: return int(s)
    except (TypeError, ValueError): return None
def rows(path):
    with zipfile.ZipFile(path) as z:
        with z.open(z.namelist()[0]) as f:
            yield from csv.DictReader(io.TextIOWrapper(f, encoding='utf-8', newline=''), delimiter='\t')
def log(s): print(s, flush=True)
def export(name, sql, args=()):
    cur=db.execute(sql,args)
    names=[d[0] for d in cur.description]
    data=[dict(zip(names,r)) for r in cur]
    with (OUT/(name+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=names);w.writeheader();w.writerows(data)
    return data

if not db.execute("SELECT 1 FROM sqlite_master WHERE name='notes'").fetchone():
    db.execute('CREATE TABLE notes(noteId TEXT PRIMARY KEY, author TEXT, created INTEGER, tweetId TEXT, classification TEXT, media INTEGER, ai INTEGER, summary TEXT, exact BLOB, body BLOB, body_len INTEGER)')
    for path in sorted(SOURCE.glob('notes-*.zip')):
        batch=[];n=0
        for r in rows(path):
            s=r['summary'];b=norm(URL.sub(' ',s))
            batch.append((r['noteId'],r['noteAuthorParticipantId'],integer(r['createdAtMillis']),r['tweetId'],r['classification'],integer(r['isMediaNote']),integer(r['isCollaborativeNote']),s,digest(norm(s)),digest(b),len(b)))
            if len(batch)>=20000:
                db.executemany('INSERT INTO notes VALUES(?,?,?,?,?,?,?,?,?,?,?)',batch);db.commit();n+=len(batch);batch=[]
                if n%400000==0:log(f'{path.name}: {n:,} notes')
        db.executemany('INSERT INTO notes VALUES(?,?,?,?,?,?,?,?,?,?,?)',batch);db.commit();log(f'{path.name}: finished {n+len(batch):,}')
    db.execute('CREATE INDEX notes_exact ON notes(exact)');db.execute('CREATE INDEX notes_body ON notes(body)');db.commit()
if not db.execute("SELECT 1 FROM sqlite_master WHERE name='status'").fetchone():
    db.execute('CREATE TABLE status(noteId TEXT PRIMARY KEY, state TEXT, known INTEGER, first_ms INTEGER, first_state TEXT, current_ms INTEGER, current_state TEXT, latest_ms INTEGER, latest_state TEXT)')
    batch=[];n=0
    for r in rows(SOURCE/'noteStatusHistory-00000.zip'):
        batch.append((r['noteId'],r['statusAsOfCutoff'],integer(r['statusAsOfCutoffKnown']),integer(r['timestampMillisOfFirstNonNMRStatus']),r['firstNonNMRStatus'],integer(r['timestampMillisOfCurrentStatus']),r['currentStatus'],integer(r['timestampMillisOfLatestNonNMRStatus']),r['mostRecentNonNMRStatus']))
        if len(batch)>=30000:
            db.executemany('INSERT INTO status VALUES(?,?,?,?,?,?,?,?,?)',batch);db.commit();n+=len(batch);batch=[]
            if n%600000==0:log(f'status: {n:,}')
    db.executemany('INSERT INTO status VALUES(?,?,?,?,?,?,?,?,?)',batch);db.commit();log('status finished')

base=export('data_scope', '''SELECT COUNT(*) notes, COUNT(DISTINCT tweetId) posts,
 MIN(created) min_created, MAX(created) max_created,
 SUM(media=1) media_notes, SUM(ai=1) collaborative_notes,
 SUM(classification='MISINFORMED_OR_POTENTIALLY_MISLEADING') misleading_notes,
 SUM(s.noteId IS NULL) missing_status, SUM(s.known=0) unknown_status,
 SUM(s.known=1 AND s.state='CURRENTLY_RATED_HELPFUL') helpful_notes
 FROM notes n LEFT JOIN status s USING(noteId)''')
export('status_by_media', '''SELECT n.media, n.classification, s.state, s.known, COUNT(*) notes,
 COUNT(DISTINCT tweetId) posts FROM notes n LEFT JOIN status s USING(noteId)
 GROUP BY n.media,n.classification,s.state,s.known''')
export('monthly_scope', '''SELECT strftime('%Y-%m',created/1000,'unixepoch') month,
 COUNT(*) notes,COUNT(DISTINCT tweetId) posts,SUM(media=1) media_notes
 FROM notes GROUP BY month''')
log(json.dumps(base))

# Candidate texts: misleading classification, >=80 non-URL characters, valid original post.
db.execute('DROP TABLE IF EXISTS eligible')
db.execute('''CREATE TABLE eligible AS SELECT n.*,s.state,s.known,s.first_ms,s.first_state,
 CASE WHEN s.current_state='CURRENTLY_RATED_HELPFUL' AND s.current_ms<=1785110399999
 THEN s.current_ms END AS stable_helpful_start
 FROM notes n LEFT JOIN status s USING(noteId)
 WHERE classification='MISINFORMED_OR_POTENTIALLY_MISLEADING'
 AND body_len>=80 AND tweetId NOT IN ('','0','-1')''')
db.execute('CREATE INDEX eligible_exact ON eligible(exact)')
db.execute('CREATE INDEX eligible_body ON eligible(body)');db.commit()
stats={}
stats['scope']=base[0]
stats['eligible']=export('eligible_scope','SELECT COUNT(*) notes, COUNT(DISTINCT tweetId) posts, SUM(known=1 AND state=\'CURRENTLY_RATED_HELPFUL\') helpful_notes FROM eligible')[0]
for key in ['exact','body']:
    log('grouping '+key)
    db.execute(f'DROP TABLE IF EXISTS groups_{key}')
    db.execute(f'''CREATE TABLE groups_{key} AS SELECT {key} key, COUNT(*) n,
     COUNT(DISTINCT tweetId) posts, COUNT(DISTINCT author) authors,
     SUM(media=1) media_notes, SUM(ai=1) ai_notes,
     SUM(known=1 AND state='CURRENTLY_RATED_HELPFUL') helpful_notes,
     COUNT(DISTINCT CASE WHEN known=1 AND state='CURRENTLY_RATED_HELPFUL' THEN tweetId END) helpful_posts,
     SUM(known=1 AND state='CURRENTLY_RATED_NOT_HELPFUL') not_helpful_notes,
     MIN(created) first_created,MAX(created) last_created,
     MIN(stable_helpful_start) stable_start
     FROM eligible GROUP BY {key} HAVING COUNT(DISTINCT tweetId)>1''')
    db.execute(f'CREATE UNIQUE INDEX groups_{key}_idx ON groups_{key}(key)');db.commit()
    stats[key]=export(key+'_summary',f'''SELECT COUNT(*) groups,SUM(n) notes,
      SUM(posts) group_post_memberships,SUM(posts-1) one_seed_per_group_extra_memberships,
      SUM(authors>1) multi_author_groups, SUM(helpful_notes>0) groups_with_helpful,
      SUM(CASE WHEN helpful_notes>0 THEN posts-1 ELSE 0 END) helpful_seed_extra_memberships,
      SUM(CASE WHEN helpful_posts>0 THEN posts-helpful_posts ELSE 0 END) without_helpful_memberships,
      MAX(posts) max_posts FROM groups_{key}''')[0]
    stats[key]['unique_posts']=db.execute(f'SELECT COUNT(DISTINCT e.tweetId) FROM eligible e JOIN groups_{key} g ON e.{key}=g.key').fetchone()[0]
    stats[key]['unique_posts_helpful_seed_groups']=db.execute(f'SELECT COUNT(DISTINCT e.tweetId) FROM eligible e JOIN groups_{key} g ON e.{key}=g.key WHERE g.helpful_notes>0').fetchone()[0]
    top=export(key+'_top_groups',f'''SELECT hex(key) group_id, n,posts,authors,media_notes,ai_notes,helpful_notes,helpful_posts,not_helpful_notes,first_created,last_created,
      (SELECT summary FROM eligible WHERE {key}=g.key ORDER BY created,noteId LIMIT 1) example_text,
      (SELECT tweetId FROM eligible WHERE {key}=g.key ORDER BY created,noteId LIMIT 1) example_post
      FROM groups_{key} g ORDER BY posts DESC LIMIT 50''')
    log(json.dumps(stats[key]))

# Exact text only for stronger retrospective potential. Current Helpful spell must have
# started before target note. Target post itself must be different. This avoids treating
# eventual Helpful status or first non-NMR status as continuous approval.
log('temporal candidates')
db.execute('DROP TABLE IF EXISTS pairs')
db.execute('''CREATE TABLE pairs AS
 WITH ranked AS (SELECT e.noteId,e.tweetId,e.exact,e.created,e.stable_helpful_start,
 ROW_NUMBER() OVER(PARTITION BY e.exact ORDER BY e.stable_helpful_start,e.noteId) rn
 FROM eligible e JOIN groups_exact g ON e.exact=g.key
 WHERE e.stable_helpful_start IS NOT NULL AND e.known=1 AND e.state='CURRENTLY_RATED_HELPFUL')
 SELECT s.noteId source_note,s.tweetId source_post,s.stable_helpful_start source_helpful_ms,
 t.noteId target_note,t.tweetId target_post,t.created target_note_ms,t.media target_media,t.ai target_ai,
 t.state target_status,t.known target_status_known, hex(t.exact) group_id,
 (t.created-s.stable_helpful_start)/3600000.0 prior_available_hours
 FROM ranked s JOIN eligible t ON s.exact=t.exact
 WHERE s.rn=1 AND t.tweetId<>s.tweetId AND t.created>s.stable_helpful_start''')
db.commit()
stats['temporal']=export('temporal_summary','''SELECT COUNT(*) target_notes,COUNT(DISTINCT target_post) target_posts,
 COUNT(DISTINCT source_note) source_notes,SUM(target_media=0) nonmedia_target_notes,
 SUM(target_status_known=1 AND target_status='CURRENTLY_RATED_HELPFUL') helpful_target_notes,
 SUM(target_status_known=1 AND target_status='CURRENTLY_RATED_NOT_HELPFUL') not_helpful_target_notes,
 SUM(target_status_known=1 AND target_status='NEEDS_MORE_RATINGS') nmr_target_notes
 FROM pairs''')[0]
export('temporal_candidates','SELECT * FROM pairs ORDER BY source_note,target_note_ms')
export('temporal_top_sources','''SELECT source_note,source_post,COUNT(DISTINCT target_post) extra_posts,COUNT(*) target_notes,
 SUM(target_media=0) nonmedia_notes,MIN(prior_available_hours) min_prior_hours,MAX(prior_available_hours) max_prior_hours,
 (SELECT summary FROM notes WHERE noteId=p.source_note) summary
 FROM pairs p GROUP BY source_note ORDER BY extra_posts DESC''')
stats['post_scope']=export('post_scope','''SELECT COUNT(DISTINCT tweetId) all_posts,
 COUNT(DISTINCT CASE WHEN known=1 AND state='CURRENTLY_RATED_HELPFUL' THEN tweetId END) helpful_posts FROM eligible''')[0]
# More efficient post-level availability lookup.
db.execute('CREATE INDEX IF NOT EXISTS notes_tweet ON notes(tweetId)');db.commit()
stats['temporal']['posts_without_any_helpful_note']=db.execute('''SELECT COUNT(DISTINCT target_post) FROM pairs p WHERE NOT EXISTS
 (SELECT 1 FROM notes n JOIN status s USING(noteId) WHERE n.tweetId=p.target_post AND s.known=1 AND s.state='CURRENTLY_RATED_HELPFUL')''').fetchone()[0]
export('audit_sample','''SELECT p.*,n.summary FROM pairs p JOIN notes n ON n.noteId=p.source_note
 ORDER BY substr(p.target_note,-5),p.target_note LIMIT 100''')
(OUT/'summary.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8')
log(json.dumps(stats,indent=2))
db.close()
