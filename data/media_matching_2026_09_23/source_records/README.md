# Source records: unchanged X field names and values

These files preserve source fields. No fields are renamed, merged, recoded or added inside the records.

- `notes.tsv.gz`: the 160,767 selected media notes, copied as complete original TSV lines from the official August 24 snapshot. Original header and row bytes are preserved. The note cohort was selected by the earlier July 26 cutoff, but the source snapshot was collected later.
- `noteStatusHistory.tsv.gz`: source status rows for the selected note IDs, with the original official header and complete row bytes. These are **August snapshot statuses**, not reconstructed July 26 statuses. No derived cutoff-status columns are added.
- `posts-*.tar.gz`: original successful syndication JSON payloads, one `<postId>.json` per entry. JSON payload bytes are copied from stored responses without parsing/reserializing or adding wrapper fields. There are 305,638 posts across these archives. These are syndication responses, not X API v2 responses. Decompress with standard tar software or Python `tarfile`.
- `manifest.json`: file checksums, sizes and record counts; this is our metadata, not an X field.

Selection and compression do not modify field names or values. Collection times and our association/display decisions remain in the separate `../derived/` tables. The main raw post collection and supplementary collections used different retrieval dates; see derived metadata for timestamps. Raw main responses were preserved in the local database and have now been added to this repository.

Original ratings are not included here: the published association tables are derived extracts, not raw rating rows. In particular, `postId` in an association table is our join field; its official source field is `ratedOnTweetId`. Do not treat the association tables as original ratings. Full rating ZIPs are large and remain external inputs to the collection scripts.

```python
import pandas as pd
import tarfile, json
notes = pd.read_csv('data/media_matching_2026_09_23/source_records/notes.tsv.gz',
                    sep='\t', dtype=str, keep_default_na=False)
with tarfile.open('data/media_matching_2026_09_23/source_records/posts-001.tar.gz') as archive:
    for member in archive:
        post = json.load(archive.extractfile(member))
        # Original fields: id_str, created_at, favorite_count, user, etc.
```
