"""Build and extend a linked media-note -> post dataset.

Sources:
1. Community Notes snapshot already normalized in outputs/reuse.sqlite.
2. Cross-post media-note rating contexts in media_matching.sqlite.
3. Existing public X syndication snapshots in full_posts.sqlite.
4. Optional additional public syndication fetches for missing linked posts.

`ratedOnTweetId` establishes an observed cross-post rating context. A stronger,
snapshot-time confirmation of platform display is recorded when the post's
birdwatch_pivot says context was added to the image/video "on another post"
and its noteId agrees with the observed link.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ROOT = Path(__file__).resolve().parents[1]
REUSE = ROOT / "outputs/reuse.sqlite"
MATCH = ROOT / "outputs/helpful_propagation/media_matching.sqlite"
EXISTING_POSTS = ROOT / "outputs/post_similarity/full_collection/full_posts.sqlite"
OUT_DIR = ROOT / "outputs/media_note_posts"
OUT_DB = OUT_DIR / "media_note_posts.sqlite"
SUMMARY = OUT_DIR / "summary.json"
ENDPOINT = "https://cdn.syndication.twimg.com/tweet-result?id={post_id}&lang=en&token=0"
LOCAL = threading.local()


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=120)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def initialize() -> sqlite3.Connection:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = connect(OUT_DB)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS media_notes(
          noteId TEXT PRIMARY KEY,
          noteAuthorId TEXT,
          noteCreatedAtMs INTEGER,
          originalPostId TEXT,
          classification TEXT,
          currentStatus TEXT,
          firstStatusAtMs INTEGER,
          stableHelpfulStartMs INTEGER,
          noteText TEXT,
          isAiAuthor INTEGER
        );
        CREATE TABLE IF NOT EXISTS note_post_links(
          noteId TEXT NOT NULL,
          postId TEXT NOT NULL,
          relationship TEXT NOT NULL,
          firstObservedRatingMs INTEGER,
          PRIMARY KEY(noteId,postId,relationship)
        );
        CREATE INDEX IF NOT EXISTS idx_links_post ON note_post_links(postId);
        CREATE INDEX IF NOT EXISTS idx_links_relationship ON note_post_links(relationship);
        CREATE TABLE IF NOT EXISTS post_payloads(
          postId TEXT PRIMARY KEY,
          fetchStatus TEXT,
          httpStatus INTEGER,
          retrievedUtc TEXT,
          payloadGzip BLOB,
          attempts INTEGER NOT NULL DEFAULT 0,
          lastError TEXT
        );
        CREATE TABLE IF NOT EXISTS post_info(
          postId TEXT PRIMARY KEY,
          createdAt TEXT,
          text TEXT,
          lang TEXT,
          authorId TEXT,
          authorScreenName TEXT,
          authorVerified INTEGER,
          favoriteCount INTEGER,
          conversationCount INTEGER,
          hasMedia INTEGER,
          mediaType TEXT,
          mediaUrlsJson TEXT,
          pivotNoteId TEXT,
          pivotTitle TEXT,
          pivotText TEXT,
          confirmedMediaMatchedShown INTEGER,
          retrievedUtc TEXT
        );
        """
    )
    con.execute("ATTACH DATABASE ? AS r", (str(REUSE),))
    con.execute("ATTACH DATABASE ? AS mm", (str(MATCH),))
    con.execute(
        """
        INSERT OR REPLACE INTO media_notes
        SELECT n.noteId,n.author,n.created,n.tweetId,n.classification,
               s.current_state,s.first_ms,NULL,n.summary,n.ai
        FROM r.notes n
        LEFT JOIN r.status s ON s.noteId=n.noteId
        WHERE n.media=1
        """
    )
    con.execute(
        """
        INSERT OR REPLACE INTO note_post_links(noteId,postId,relationship,firstObservedRatingMs)
        SELECT noteId,originalPostId,'original',noteCreatedAtMs
        FROM media_notes WHERE originalPostId IS NOT NULL AND originalPostId!=''
        """
    )
    con.execute(
        """
        INSERT OR REPLACE INTO note_post_links(noteId,postId,relationship,firstObservedRatingMs)
        SELECT m.noteId,m.targetPostId,'matched_rating_context',m.firstRatingMs
        FROM mm.matched_posts m JOIN media_notes n ON n.noteId=m.noteId
        """
    )
    con.commit()
    return con


def import_existing(con: sqlite3.Connection) -> int:
    con.execute("ATTACH DATABASE ? AS fp", (str(EXISTING_POSTS),))
    before = con.execute("SELECT COUNT(*) FROM post_payloads").fetchone()[0]
    con.execute(
        """
        INSERT OR IGNORE INTO post_payloads
        SELECT p.post_id,p.fetch_status,p.http_status,p.retrieved_utc,
               p.payload_gzip,p.attempts,p.last_error
        FROM fp.posts p
        JOIN (SELECT DISTINCT postId FROM note_post_links) l ON l.postId=p.post_id
        """
    )
    con.commit()
    after = con.execute("SELECT COUNT(*) FROM post_payloads").fetchone()[0]
    return after - before


def normalize_one(
    con: sqlite3.Connection, post_id: str, retrieved: str, blob: bytes,
    linked_notes: set[str] | None = None,
) -> None:
    obj = json.loads(gzip.decompress(blob))
    user = obj.get("user") or {}
    media = obj.get("mediaDetails") or []
    urls = []
    types = []
    for item in media:
        url = item.get("media_url_https") or item.get("expanded_url")
        if url:
            urls.append(url)
        types.append(item.get("type") or "")
    if obj.get("video"):
        media_type = "video"
    elif obj.get("photos") or media:
        media_type = "image"
    else:
        media_type = "none"
    pivot = obj.get("birdwatch_pivot") or {}
    pivot_note = str(pivot.get("noteId") or "")
    title = str(pivot.get("title") or "")
    subtitle = pivot.get("subtitle") or {}
    pivot_text = subtitle.get("text") if isinstance(subtitle, dict) else None
    if linked_notes is None:
        linked_notes = {
            str(r[0]) for r in con.execute(
                "SELECT noteId FROM note_post_links WHERE postId=? AND relationship='matched_rating_context'",
                (post_id,),
            )
        }
    confirmed = int(
        bool(pivot_note)
        and pivot_note in linked_notes
        and "another post" in title.lower()
    )
    con.execute(
        """
        INSERT OR REPLACE INTO post_info VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            post_id,obj.get("created_at"),obj.get("text"),obj.get("lang"),
            user.get("id_str"),user.get("screen_name"),
            int(bool(user.get("verified") or user.get("is_blue_verified"))),
            obj.get("favorite_count"),obj.get("conversation_count"),
            int(media_type != "none"),media_type,json.dumps(urls,ensure_ascii=False),
            pivot_note or None,title or None,pivot_text,confirmed,retrieved,
        ),
    )


def normalize_all(con: sqlite3.Connection) -> int:
    done = {r[0] for r in con.execute("SELECT postId FROM post_info")}
    target_notes: dict[str, set[str]] = {}
    for note_id, post_id in con.execute(
        "SELECT noteId,postId FROM note_post_links WHERE relationship='matched_rating_context'"
    ):
        target_notes.setdefault(str(post_id), set()).add(str(note_id))
    n = 0
    for post_id, retrieved, blob in con.execute(
        "SELECT postId,retrievedUtc,payloadGzip FROM post_payloads "
        "WHERE fetchStatus='ok' AND payloadGzip IS NOT NULL"
    ):
        if post_id in done:
            continue
        normalize_one(con, post_id, retrieved, blob, target_notes.get(str(post_id), set()))
        n += 1
        if n % 1000 == 0:
            con.commit()
    con.commit()
    return n


def session() -> requests.Session:
    if not hasattr(LOCAL, "session"):
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0"})
        retry = Retry(
            total=2,connect=2,read=1,backoff_factor=.3,
            status_forcelist=(429,500,502,503,504),allowed_methods=("GET",),
        )
        s.mount("https://", HTTPAdapter(max_retries=retry,pool_connections=1,pool_maxsize=1))
        LOCAL.session = s
    return LOCAL.session


def fetch(post_id: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    try:
        response = session().get(ENDPOINT.format(post_id=post_id), timeout=15)
        status = response.status_code
        response.raise_for_status()
        obj = response.json()
        valid = obj.get("id_str") == post_id and isinstance(obj.get("text"), str)
        return {
            "postId": post_id,"fetchStatus": "ok" if valid else "unavailable",
            "httpStatus": status,"retrievedUtc": now,
            "payloadGzip": gzip.compress(json.dumps(obj,ensure_ascii=False).encode("utf-8")),
            "lastError": None,
        }
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return {"postId":post_id,"fetchStatus":"error","httpStatus":status,
                "retrievedUtc":now,"payloadGzip":None,"lastError":repr(exc)}


def missing_manifest(con: sqlite3.Connection, limit: int) -> list[str]:
    rows = con.execute(
        """
        SELECT l.postId,
               MAX(l.relationship='matched_rating_context') AS is_target,
               MAX(CASE WHEN l.relationship='matched_rating_context'
                         AND n.currentStatus='CURRENTLY_RATED_HELPFUL' THEN 1 ELSE 0 END) AS helpful_target
        FROM note_post_links l
        JOIN media_notes n ON n.noteId=l.noteId
        LEFT JOIN post_payloads p ON p.postId=l.postId
        WHERE p.postId IS NULL OR (p.fetchStatus='error' AND p.attempts<3)
        GROUP BY l.postId
        ORDER BY helpful_target DESC,is_target DESC,l.postId
        """
    ).fetchall()
    ids = [str(r[0]) for r in rows]
    return ids[:limit] if limit else ids


def fetch_missing(con: sqlite3.Connection, limit: int, workers: int) -> int:
    ids = missing_manifest(con, limit)
    if not ids:
        return 0
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(fetch, ids):
            con.execute(
                """
                INSERT INTO post_payloads VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(postId) DO UPDATE SET
                  fetchStatus=excluded.fetchStatus,httpStatus=excluded.httpStatus,
                  retrievedUtc=excluded.retrievedUtc,payloadGzip=excluded.payloadGzip,
                  attempts=post_payloads.attempts+1,lastError=excluded.lastError
                """,
                (result["postId"],result["fetchStatus"],result["httpStatus"],
                 result["retrievedUtc"],result["payloadGzip"],1,result["lastError"]),
            )
            completed += 1
            if completed % 200 == 0:
                con.commit()
    con.commit()
    return completed


def fetch_confirmed_origins(con: sqlite3.Connection, workers: int) -> int:
    ids = [str(r[0]) for r in con.execute(
        """
        SELECT DISTINCT n.originalPostId
        FROM post_info target
        JOIN media_notes n ON n.noteId=target.pivotNoteId
        LEFT JOIN post_payloads p ON p.postId=n.originalPostId
        WHERE target.confirmedMediaMatchedShown=1
          AND n.originalPostId IS NOT NULL AND n.originalPostId!=''
          AND (p.postId IS NULL OR (p.fetchStatus='error' AND p.attempts<3))
        """
    )]
    if not ids:
        return 0
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(fetch, ids):
            con.execute(
                """
                INSERT INTO post_payloads VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(postId) DO UPDATE SET
                  fetchStatus=excluded.fetchStatus,httpStatus=excluded.httpStatus,
                  retrievedUtc=excluded.retrievedUtc,payloadGzip=excluded.payloadGzip,
                  attempts=post_payloads.attempts+1,lastError=excluded.lastError
                """,
                (result["postId"],result["fetchStatus"],result["httpStatus"],
                 result["retrievedUtc"],result["payloadGzip"],1,result["lastError"]),
            )
            completed += 1
            if completed % 200 == 0:
                con.commit()
    con.commit()
    return completed


def fetch_all_media_note_origins(con: sqlite3.Connection, workers: int) -> int:
    """Fetch every distinct original post referenced by a media note.

    The query is resumable: posts with a stored success/unavailable result are
    skipped, while transient errors are retried up to three total attempts.
    """
    ids = [str(r[0]) for r in con.execute(
        """
        SELECT DISTINCT n.originalPostId
        FROM media_notes n
        LEFT JOIN post_payloads p ON p.postId=n.originalPostId
        WHERE n.originalPostId IS NOT NULL AND n.originalPostId!=''
          AND (p.postId IS NULL OR (p.fetchStatus='error' AND p.attempts<3))
        ORDER BY n.originalPostId
        """
    )]
    total = len(ids)
    if not ids:
        print("All media-note original posts have already been attempted.", flush=True)
        return 0
    print(f"Fetching {total:,} missing media-note original posts...", flush=True)
    completed = 0
    status_counts = {"ok": 0, "unavailable": 0, "error": 0}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(fetch, ids):
            con.execute(
                """
                INSERT INTO post_payloads VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(postId) DO UPDATE SET
                  fetchStatus=excluded.fetchStatus,httpStatus=excluded.httpStatus,
                  retrievedUtc=excluded.retrievedUtc,payloadGzip=excluded.payloadGzip,
                  attempts=post_payloads.attempts+1,lastError=excluded.lastError
                """,
                (result["postId"],result["fetchStatus"],result["httpStatus"],
                 result["retrievedUtc"],result["payloadGzip"],1,result["lastError"]),
            )
            completed += 1
            status_counts[result["fetchStatus"]] = status_counts.get(result["fetchStatus"], 0) + 1
            if completed % 200 == 0:
                con.commit()
            if completed % 1000 == 0 or completed == total:
                print(
                    f"Progress {completed:,}/{total:,} "
                    f"(ok={status_counts.get('ok',0):,}, "
                    f"unavailable={status_counts.get('unavailable',0):,}, "
                    f"error={status_counts.get('error',0):,})",
                    flush=True,
                )
    con.commit()
    return completed


def summarize(con: sqlite3.Connection) -> dict:
    def scalar(sql: str) -> int:
        return int(con.execute(sql).fetchone()[0])
    result = {
        "media_notes": scalar("SELECT COUNT(*) FROM media_notes"),
        "media_note_original_posts": scalar("SELECT COUNT(DISTINCT originalPostId) FROM media_notes"),
        "cross_post_note_post_links": scalar("SELECT COUNT(*) FROM note_post_links WHERE relationship='matched_rating_context'"),
        "unique_matched_target_posts": scalar("SELECT COUNT(DISTINCT postId) FROM note_post_links WHERE relationship='matched_rating_context'"),
        "all_unique_linked_posts": scalar("SELECT COUNT(DISTINCT postId) FROM note_post_links"),
        "post_payload_rows": scalar("SELECT COUNT(*) FROM post_payloads"),
        "post_payload_ok": scalar("SELECT COUNT(*) FROM post_payloads WHERE fetchStatus='ok'"),
        "normalized_post_info": scalar("SELECT COUNT(*) FROM post_info"),
        "confirmed_media_matched_shown": scalar("SELECT COUNT(*) FROM post_info WHERE confirmedMediaMatchedShown=1"),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    SUMMARY.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch-limit",type=int,default=0,help="0 initializes/imports only")
    ap.add_argument("--workers",type=int,default=16)
    ap.add_argument("--fetch-confirmed-origins",action="store_true")
    ap.add_argument("--fetch-all-origins",action="store_true")
    args = ap.parse_args()
    con = initialize()
    imported = import_existing(con)
    normalized_before = normalize_all(con)
    fetched = fetch_missing(con,args.fetch_limit,args.workers) if args.fetch_limit else 0
    fetched_origins = fetch_confirmed_origins(con,args.workers) if args.fetch_confirmed_origins else 0
    fetched_all_origins = fetch_all_media_note_origins(con,args.workers) if args.fetch_all_origins else 0
    normalized_after = normalize_all(con)
    summary = summarize(con)
    con.close()
    print(json.dumps({"imported_existing":imported,"normalized_existing":normalized_before,
                      "fetched":fetched,"fetched_confirmed_origins":fetched_origins,
                      "fetched_all_origins":fetched_all_origins,
                      "normalized_new":normalized_after,**summary},
                     ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
