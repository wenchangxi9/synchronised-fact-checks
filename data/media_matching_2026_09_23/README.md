# Media notes and associated posts

Export prepared September 23, 2026. This package contains the **media-note cohort**, not all Community Notes. Source: official Community Notes snapshot downloaded August 24, 2026, reconstructed with a July 26, 2026 UTC creation cutoff. Post information was collected separately from X's public syndication endpoint. Records are observational snapshots, not an exhaustive archive of platform displays.

## Files

|File|Contents|
|---|---|
|media_notes.csv.gz|160,767 media notes, including text, pseudonymous author IDs, original post ID, and available status fields|
|links_cutoff.csv.gz|Original post links and distinct cross-post rating associations through the July 26 cutoff|
|posts.csv.gz|304,940 successfully retrieved posts, with text, timestamps, authors, available engagement counts, media URLs and display metadata|
|fetch_log.csv.gz|Original collection attempt outcomes, including failures|
|links_extended.csv.gz|639 additional associations for the same note cohort from the full August snapshot; observation window differs from the cutoff table|
|supplemental_posts.jsonl.gz|Additional successful post responses from old caches, extended observation and failure retries; each line contains postId, retrievedUtc and the returned payload|
|verified_display.csv.gz|43,198 distinct posts associated with 10,395 notes, verified using returned cross-post display metadata and original media-note records|
|manifest.json|Exact row counts, compressed sizes and SHA-256 checksums|

The extended candidate association set contains 273,907 posts and 55,526 notes. The display set also includes posts discovered in other collected sources, so these are not interchangeable denominators. Additional association timestamps run from July 27 to August 22, 2026.

## How to join

Read all IDs as strings. Join links to notes using `noteId`; join links or display evidence to posts using `postId`. Supplementary responses use X's raw field names (`id_str`, `created_at`, `user`, `birdwatch_pivot`, etc.). All posts in `verified_display.csv.gz` exist in either `posts.csv.gz` or the supplementary file, and all its notes exist in `media_notes.csv.gz`; these relationships were checked before export.

```python
from pathlib import Path
import pandas as pd
import gzip, json

d = Path('data/media_matching_2026_09_23')
notes = pd.read_csv(d / 'media_notes.csv.gz', dtype=str)
posts = pd.read_csv(d / 'posts.csv.gz', dtype=str)
links = pd.read_csv(d / 'links_cutoff.csv.gz', dtype=str)
display = pd.read_csv(d / 'verified_display.csv.gz', dtype=str)
with gzip.open(d / 'supplemental_posts.jsonl.gz', 'rt', encoding='utf-8') as f:
    supplemental = [json.loads(line) for line in f]
```

## Important field definitions

- `originalPostId`: `tweetId` from the official note record; the post where the note was originally submitted.
- `relationship=original`: original submission link. `relationship=matched_rating_context`: a rating's `ratedOnTweetId` differs from the original post for the same note. It establishes a cross-post rating context, not independently a public display.
- `firstObservedRatingMs`: earliest observed rating for the association, Unix milliseconds. **Not the time matching began or the time the note first displayed.**
- `noteCreatedAtMs`: note submission time in Unix milliseconds. Post `createdAt` is post publication time; `retrievedUtc` is collection time.
- `isCollaborativeNote`: official collaborative-note indicator. It was misleadingly named `isAiAuthor` in an earlier local database; this export corrects the name. **Do not treat it as an AI author flag.**
- `currentStatus`: imported status used in the cutoff analysis; missing values remain unknown. Do not interpret it as status at post retrieval. `firstStatusAtMs` concerns the first non-NMR status, not necessarily Helpful. `stableHelpfulStartMs` is a derived legacy field and should not be used as target-post display time.
- `authorVerified`: legacy normalization combines verified and blue-verified flags; not a clean measure of identity verification.
- `favoriteCount` and `conversationCount`: returned snapshot counts, not engagement histories. Do not interpret conversationCount as repost count. There are no individual like/repost timestamps in this export.
- `mediaType` and `hasMedia`: legacy derived summaries; inspect raw supplementary media fields where exact media categorization matters.
- `confirmedMediaMatchedShown`: **legacy strict flag** requiring a note ID match to an existing rating association. Use `verified_display.csv.gz` for the expanded audited evidence set instead.

## Display evidence and limitations

Display evidence requires an English `birdwatch_pivot` title referring to media on another post, a returned note ID matching an official media note, and a target post different from the note's original post. This is interface-returned metadata, not independent browser verification. Missing metadata does **not** establish that a post never displayed a note. Do not label missing/failed posts as untreated controls.

HTTP errors and empty responses do not reveal whether a post was deleted, restricted or unavailable because of endpoint limitations. Counts at retrieval do not establish causal effects. Post media files are not bundled; only returned URLs/metadata are included. The original large SQLite and raw main-collection payloads are retained locally; this package provides normalized main data plus supplementary raw responses.

Official source documentation: https://communitynotes.x.com/guide/en/under-the-hood/download-data

Publicly accessible source content is not a grant of unrestricted reuse rights; this repository does not assign a new license to third-party post content.
