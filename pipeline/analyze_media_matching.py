"""Identify observed cross-post media-note matches from ratedOnTweetId."""

from __future__ import annotations

import sqlite3
import time
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path('source/cutoff_zip')
REUSE_DB = ROOT / "outputs" / "reuse.sqlite"
OUT_DB = ROOT / "outputs" / "helpful_propagation" / "media_matching.sqlite"


def main() -> None:
    source = sqlite3.connect(REUSE_DB)
    media_rows = source.execute("SELECT noteId,tweetId FROM notes WHERE media=1").fetchall()
    source.close()
    origin = {str(note): str(tweet) for note, tweet in media_rows}
    value_set = pa.array(list(origin), type=pa.string())
    print(f"media notes: {len(origin):,}", flush=True)

    db = sqlite3.connect(OUT_DB)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute(
        "CREATE TABLE IF NOT EXISTS matched_posts(noteId TEXT, targetPostId TEXT, "
        "firstRatingMs INTEGER, PRIMARY KEY(noteId,targetPostId))"
    )
    db.execute("CREATE TABLE IF NOT EXISTS completed_files(filename TEXT PRIMARY KEY)")
    completed = {r[0] for r in db.execute("SELECT filename FROM completed_files")}

    options = pacsv.ConvertOptions(
        include_columns=["noteId", "createdAtMillis", "ratedOnTweetId"],
        column_types={"noteId": pa.string(), "createdAtMillis": pa.int64(), "ratedOnTweetId": pa.string()},
        strings_can_be_null=True,
    )
    read_options = pacsv.ReadOptions(block_size=64 * 1024 * 1024, use_threads=True)
    parse_options = pacsv.ParseOptions(delimiter="\t")

    for path in sorted(SOURCE.glob("ratings-*.zip")):
        if path.name in completed:
            print(f"skip {path.name}", flush=True)
            continue
        started = time.time()
        scanned = kept = 0
        with zipfile.ZipFile(path) as archive:
            with archive.open(archive.namelist()[0]) as handle:
                reader = pacsv.open_csv(handle, read_options=read_options,
                                        parse_options=parse_options, convert_options=options)
                for batch in reader:
                    scanned += batch.num_rows
                    mask = pc.is_in(batch.column("noteId"), value_set=value_set)
                    selected = batch.filter(mask)
                    if not selected.num_rows:
                        continue
                    notes = selected.column("noteId").to_pylist()
                    targets = selected.column("ratedOnTweetId").to_pylist()
                    times = selected.column("createdAtMillis").to_pylist()
                    rows = []
                    for note, target, timestamp in zip(notes, targets, times):
                        if target and target not in ("0", "-1") and target != origin.get(note):
                            rows.append((note, target, timestamp))
                    kept += len(rows)
                    db.executemany(
                        "INSERT INTO matched_posts VALUES(?,?,?) "
                        "ON CONFLICT(noteId,targetPostId) DO UPDATE SET "
                        "firstRatingMs=min(firstRatingMs,excluded.firstRatingMs)", rows
                    )
                db.commit()
        db.execute("INSERT INTO completed_files VALUES(?)", (path.name,))
        db.commit()
        unique_pairs = db.execute("SELECT COUNT(*) FROM matched_posts").fetchone()[0]
        print(f"{path.name}: rows={scanned:,}, cross-post ratings={kept:,}, "
              f"unique pairs total={unique_pairs:,}, elapsed={time.time()-started:.1f}s", flush=True)

    db.close()


if __name__ == "__main__":
    main()
