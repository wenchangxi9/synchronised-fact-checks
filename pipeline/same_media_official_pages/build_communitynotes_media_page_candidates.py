"""Build candidate X same-media pages from the collected media-note IDs.

The /m/{noteId} route is empirically verified for sample media notes, but a
candidate route is not evidence that X currently lists matching posts there.
"""

import csv
import gzip
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "github_sync/data/media_matching_2026_09_23/source_records/notes.tsv.gz"
STATUS_SOURCE = ROOT / "outputs/media_note_posts/all_media_notes_with_original_posts.csv"
OUTPUT = ROOT / "outputs/communitynotes_media_pages/media_note_page_candidates.csv"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with STATUS_SOURCE.open(encoding="utf-8-sig", newline="") as source:
        current_status = {
            row["noteId"]: row["currentStatus"]
            for row in csv.DictReader(source)
        }
    total = 0
    helpful = 0
    with gzip.open(SOURCE, "rt", encoding="utf-8", newline="") as source, OUTPUT.open(
        "w", encoding="utf-8-sig", newline=""
    ) as target:
        reader = csv.DictReader(source, delimiter="\t")
        writer = csv.writer(target)
        writer.writerow(
            ["noteId", "originalPostId", "noteCreatedAtMillis", "currentStatus", "candidateMediaPageUrl"]
        )
        for row in reader:
            if row["isMediaNote"] != "1":
                continue
            note_id = row["noteId"].strip()
            if not note_id.isdigit():
                continue
            writer.writerow(
                [
                    note_id,
                    row["tweetId"],
                    row["createdAtMillis"],
                    current_status.get(note_id, ""),
                    f"https://x.com/i/communitynotes/m/{note_id}",
                ]
            )
            total += 1
            helpful += current_status.get(note_id) == "CURRENTLY_RATED_HELPFUL"
    print(f"Candidate pages: {total:,}; currently Helpful: {helpful:,}")
    print(OUTPUT)


if __name__ == "__main__":
    main()
