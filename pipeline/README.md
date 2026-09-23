# Collection, processing and validation code

These scripts produced the released media-note dataset. Paths were adapted to the repository layout; original collection and audit logic is retained. No API credentials are bundled. Run commands from the repository root with Python 3.12.

## Validate the uploaded dataset immediately

```sh
python pipeline/verify_release.py
```

Uses only Python's standard library and published files. Checks SHA-256 hashes, row counts, unique display posts, and that every display association has a note and available post. It does not revalidate live X displays.

## Collection provenance and execution order

Install collection dependencies with `python -m pip install -r pipeline/requirements.txt`.

The full collection workflow requires large local inputs not included in this repository: the original August 24, 2026 official snapshot ZIPs in `source/raw_snapshot/`, and the preprocessed July 26 cutoff ZIPs in `source/cutoff_zip/`. The latter include derived cutoff status fields. This repository does not recreate that prior snapshot preparation step. The original cached post database, where used, is `outputs/post_similarity/full_collection/full_posts.sqlite`.

|Order / script|Purpose|
|---|---|
|1. explore_reuse.py|Import cutoff notes/status into outputs/reuse.sqlite; also performs older descriptive text grouping|
|2. analyze_media_matching.py|Scan ratings for media-note cross-post associations|
|3. prepare_media_note_post_dataset.py|Build media-note/post database, import available caches, optionally fetch posts and normalize metadata|
|4. audit_note_display.py|Compare original payloads to parsed metadata and repeat sampled requests|
|5. repair_display_evidence.py|Identify cross-post display independently of legacy association membership; retry failed samples|
|6. expand_media_observation.py|Scan full snapshot for additional associations in the original note cohort, then retrieve new posts|
|7. scan_cached_display.py|Look for additional displays in the older local post cache|
|8. build_display_union.py|Combine audited display records and prepare successful retry list|
|9. package_github_data.py|Export release tables and checksums to data/media_matching_2026_09_23; overwrites existing release files|

Each script is invoked as `python pipeline/SCRIPT_NAME.py`. Step 3 defaults to importing/normalizing without new requests. `--fetch-limit 300000 --fetch-all-origins` enables candidate and original post collection; `--workers` controls concurrency. Steps 4–6 make public network requests. Responses change over time, so rerunning collection cannot guarantee historical counts or identical file hashes. Preserve the published release when running new collections.

The package includes the actual historical workflows, including their limitations. In legacy databases `isAiAuthor` is a mislabeled collaborative-note field; the release exporter renames it to `isCollaborativeNote`. Legacy strict display flags are superseded by the audited display union. Never use missing metadata as a verified untreated group. See the dataset README for timestamps, status limitations and engagement-field definitions. These scripts do not establish causal effects or identify historical display start times.

The former regression/figure experiments are not part of this release pipeline and are deliberately not represented as validated analyses of these data.
