# Same-Media Capture Chrome Extension

This unpacked Chrome extension collects X's official "Posts with the same media" groups from Community Notes pages:

`https://x.com/i/communitynotes/m/{noteId}`

It is intended to be run in a Chrome profile already logged in to X. The dashboard accepts a CSV with a `noteId` column, opens each official page, records the page's same-media list responses, and downloads JSON batches.

Current version: `0.2.0`.

Key behavior:

- Uses the official page and its same-media pagination responses.
- Exports JSON batches every 25 notes.
- Continues past incomplete pages where possible and records partial status for retry.
- Writes shard-aware filenames, for example `batch_shard_01_0001.json`.
- Does not export passwords, cookies, or request headers.

The ten shard CSVs and current parsed outputs are in:

`data/same_media_official_pages_2026_09_30`
