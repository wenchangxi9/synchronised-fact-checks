"""Summarize X's observed same-media GraphQL slices saved by the Chrome collector.

Only a returned terminal slice (slice_info without next_cursor) confirms that
all currently accessible pages were fetched. A missing response is never an
empty group. The parser does not use ratings or media-URL similarity.
"""

import argparse
import csv
import json
from pathlib import Path


def read_page(page):
    post_ids = []
    unavailable = 0
    empty_items = 0
    cursors = []
    terminal = False
    valid_slices = 0
    for response in page.get("responses", []):
        data = response.get("json", {}).get("data", {})
        match = data.get("authenticated_birdwatch_match") or data.get("birdwatch_media_match") or {}
        slice_data = match.get("media_cluster_search_result_slice") or {}
        info = slice_data.get("slice_info")
        items = slice_data.get("tweets_results")
        if response.get("status") != 200 or not isinstance(info, dict) or not isinstance(items, list):
            continue
        valid_slices += 1
        cursor = info.get("next_cursor")
        cursors.append(cursor)
        if not cursor:
            terminal = True
        for item in items:
            result = item.get("result") or {}
            post_id = result.get("rest_id")
            if post_id and str(post_id).isdigit():
                post_ids.append(str(post_id))
            elif result.get("__typename") == "TweetUnavailable":
                unavailable += 1
            else:
                empty_items += 1
    empty_text = page.get("lastPageState", {}).get("bodyPreview", "").lower()
    empty_notice = (page.get("lastPageState", {}).get("emptyNotice") is True or
                    "doesn’t have any matches yet" in empty_text or
                    "doesn't have any matches yet" in empty_text or
                    "还没有任何匹配项" in empty_text)
    matched_response = any(
        response.get("status") == 200 and
        str((response.get("json", {}).get("data", {}).get("authenticated_birdwatch_match") or
             response.get("json", {}).get("data", {}).get("birdwatch_media_match") or {}).get("rest_id")) == str(page.get("noteId"))
        for response in page.get("responses", [])
    )
    # X sometimes returns the match object with no slice at all for an empty
    # list. Require both the page's explicit empty notice and a 200 response
    # for this note before treating that case as a confirmed empty group.
    explicit_empty = (not post_ids and empty_notice and
                      (valid_slices > 0 or matched_response))
    completion_basis = "terminal_slice" if terminal else "explicit_empty_page" if explicit_empty else ""
    return {
        "postIds": list(dict.fromkeys(post_ids)),
        "validSlices": valid_slices,
        "complete": terminal or explicit_empty,
        "completionBasis": completion_basis,
        "lastCursor": cursors[-1] if cursors else None,
        "unavailableItems": unavailable,
        "emptyItems": empty_items,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    candidates = []
    for path in sorted(args.input_dir.glob("batch_*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for page in document.get("pages", []):
            note_id = str(page.get("noteId", ""))
            if not note_id.isdigit():
                continue
            result = read_page(page)
            result.update(noteId=note_id, pageUrl=page.get("pageUrl", ""), sourceFile=path.name,
                          capturedAt=document.get("capturedAt", ""), collectorStatus=page.get("status", ""))
            candidates.append(result)

    # Prefer a complete run over a more recent incomplete one for each note.
    by_note = {}
    for candidate in candidates:
        key = candidate["noteId"]
        current = by_note.get(key)
        rank = (candidate["complete"], candidate["validSlices"], candidate["capturedAt"])
        if current is None or rank > (current["complete"], current["validSlices"], current["capturedAt"]):
            by_note[key] = candidate

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.output_dir / "browser_capture_summary.csv"
    posts_path = args.output_dir / "browser_capture_posts.csv"
    with summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["noteId", "pageUrl", "capturedAt", "sourceFile", "complete", "completionBasis",
                                                   "postCount", "validSlices", "lastCursor", "unavailableItems",
                                                   "emptyItems", "collectorStatus"])
        writer.writeheader()
        for result in sorted(by_note.values(), key=lambda x: x["noteId"]):
            writer.writerow({"noteId": result["noteId"], "pageUrl": result["pageUrl"],
                             "capturedAt": result["capturedAt"], "sourceFile": result["sourceFile"],
                             "complete": int(result["complete"]), "completionBasis": result["completionBasis"], "postCount": len(result["postIds"]),
                             "validSlices": result["validSlices"], "lastCursor": result["lastCursor"],
                             "unavailableItems": result["unavailableItems"], "emptyItems": result["emptyItems"],
                             "collectorStatus": result["collectorStatus"]})
    with posts_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["noteId", "postId", "postUrl", "complete", "sourceFile"])
        writer.writeheader()
        for result in sorted(by_note.values(), key=lambda x: x["noteId"]):
            for post_id in result["postIds"]:
                writer.writerow({"noteId": result["noteId"], "postId": post_id,
                                 "postUrl": f"https://x.com/i/status/{post_id}",
                                 "complete": int(result["complete"]), "sourceFile": result["sourceFile"]})
    print(f"records={len(candidates)} note_pages={len(by_note)} complete={sum(x['complete'] for x in by_note.values())} ")
    print(f"summary={summary_path}\nposts={posts_path}")


if __name__ == "__main__":
    main()
