# Official X "Posts With The Same Media" Capture

This folder contains the handoff package for collecting official same-media post groups from X Community Notes pages:

`https://x.com/i/communitynotes/m/{noteId}`

The grouping here is based on X's own "Posts with the same media" page, not on `ratedOnTweetId` and not on locally scraped media URLs.

## Current Snapshot

Generated on 2026-09-30.

- Candidate media notes: 160,767
- Remaining queue after pilot/sample exclusions: 160,756
- Pages represented in the current browser capture summary: 203
- Complete pages: 200
- Complete empty pages: 30
- Complete one-post pages: 27
- Complete pages with 2+ posts: 143
- Complete note-post rows: 6,146
- Incomplete pages currently present in the parsed summary: 3

The parsed capture files are partial progress only. They are useful for checking that the browser extension works and for early inspection, but they are not a finished dataset.

## Files

- `media_note_page_candidates.csv`: all candidate Community Notes rows used to identify `isMediaNote=1` notes.
- `remaining_media_note_ids.csv`: queue of media-note IDs prepared for official page crawling.
- `parallel_shards_10/shard_01.csv` ... `shard_10.csv`: ten disjoint queues for running ten Chrome windows in parallel.
- `browser_capture_summary.csv`: one row per note page observed in downloaded browser capture batches.
- `browser_capture_posts.csv`: parsed note-post rows from complete and partial browser capture batches.
- `README_zh.md`: earlier Chinese notes about the official media-page crawling attempt.

## Continue Crawling

Load the Chrome extension from:

`tools/same_media_capture_extension`

Then open ten extension dashboard pages in the same logged-in Chrome profile. Select one shard CSV per dashboard:

- dashboard 1: `parallel_shards_10/shard_01.csv`
- dashboard 2: `parallel_shards_10/shard_02.csv`
- ...
- dashboard 10: `parallel_shards_10/shard_10.csv`

Set the per-run limit high enough to cover the shard, for example `200000`, then start each dashboard. The extension downloads result batches into the browser download folder under:

`same_media_capture/`

Version `0.2.0` writes shard-aware filenames such as:

`batch_shard_03_0001.json`

## Parse Downloaded Batches

After new JSON batches are downloaded, parse them with:

```bash
python pipeline/same_media_official_pages/parse_browser_same_media_capture.py path/to/same_media_capture data/same_media_official_pages_2026_09_30
```

This refreshes:

- `browser_capture_summary.csv`
- `browser_capture_posts.csv`

The parser treats `pagination_complete` and explicit empty pages as complete. Large or stalled pages may be saved as partial and should not be counted as final official groups until rechecked.

## Important Cautions

- Do not infer that all 160,767 candidate media notes have multiple same-media posts.
- Do not mix this official-page grouping with `ratedOnTweetId` grouping; they answer different questions.
- The raw browser capture JSON files are not included in this handoff package because they are large and are still being generated locally.
- The extension does not export passwords, cookies, or request headers. It temporarily reuses in-memory request headers only inside the logged-in browser page to continue pagination.
