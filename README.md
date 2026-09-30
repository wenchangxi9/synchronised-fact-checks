# synchronised-fact-checks

Community Notes media-note and cross-post association research data.

See [dataset documentation](data/media_matching_2026_09_23/README.md) for files, coverage, field definitions and limitations.

Collection, processing, export and verification scripts are in [pipeline](pipeline/README.md). Run `python pipeline/verify_release.py` to validate the published files and note/post joins.

## Current same-media official-page handoff

The 2026-09-30 handoff for X's official "Posts with the same media" pages is in:

- [data/same_media_official_pages_2026_09_30](data/same_media_official_pages_2026_09_30/README.md)
- [tools/same_media_capture_extension](tools/same_media_capture_extension/README.md)
- [pipeline/same_media_official_pages](pipeline/same_media_official_pages/)

This handoff includes the Chrome extension, ten disjoint queue shards for parallel crawling, current parsed progress, and parsing scripts. It uses X's official `/i/communitynotes/m/{noteId}` pages rather than `ratedOnTweetId` associations.
