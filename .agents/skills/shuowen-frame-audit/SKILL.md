---
name: shuowen-frame-audit
description: Audit and safely repair boxed seal-script characters and Shidian gloss labels in this project’s Shuowen Guangyi volumes. Use when a user says a page has extra or missing frames, wrong column order, duplicated/missing gloss characters, or asks to find suspect pages before modifying annotations.
---

# 说文广义框与释文审计

Use this skill for the project’s `程德洽-篆书-说文广义*` work directories. Treat a **physical column** as one character: every frame in that column must share one `char`.

## Non-negotiable rules

- Read page order from ascending page number and physical x coordinate from right to left. Do not trust historic `column` values as reading order.
- Separate three operations: frame existence, frame geometry, and gloss labels. Never silently combine them.
- Use downloaded Shidian glosses plus `shidian-gloss-resolutions.json` for labels. Do not OCR labels from the scan.
- The label stream is **zero-filter**: every valid one-character Shidian headword, including an independent radical/component, consumes one physical column. The only entries skipped are explicit `{"kind": "continuation"}` rules in `shidian-gloss-resolutions.json`.
- Do not change `bbox`, `row`, or `column` while only repairing `char` values.
- Before modifying, report candidates and wait for the user to confirm, unless they explicitly tell you to apply a specified repair.
- Back up `chars.json` before every write. Existing project scripts do this; preserve that behavior in new scripts.

## Identify real problems

Recover the page’s vertical grid first. Classify every grid slot as seal script, gloss text, empty, or border/noise.

Classify a column as **certainly extra** only when its frames fall in a dense small-text (gloss) slot, or when its x position is one standard grid pitch from confirmed seal columns that are normally separated by a gloss slot. A short edge gap alone is not proof.

Classify a **missing column** only when an unboxed slot contains at least two large glyph regions matching the page’s seal-column width and row baseline. A missing frame within an existing column requires a matching unboxed glyph at a supported row baseline.

Use confirmed characters as anchors. Between two anchors, compare the source-label count with physical-column count. If the difference is `k`, accept a batch of missing-column candidates only when exactly `k` image-supported candidates occur in that interval. Do not infer missing columns from count alone.

## Safe workflow

1. Inspect only. Report page, physical position, expected character, and image evidence. Reject edge-only and border-only candidates.
2. After confirmation, add/delete only the named frame columns.
3. Run the label-stream preflight. It must show that component headwords are included and that the source/slot difference is understood.
4. Reflow labels once from the earliest changed page using the corrected Shidian source; do not hand-shift only part of a later range.
5. Verify: one non-empty label per physical column; no mixed labels in a column; source/slot difference is zero or explicitly recorded.
6. If a source entry is wrong, add an explicit `headword` or `continuation` rule to `shidian-gloss-resolutions.json`, then reflow from the affected page.

## Project commands

Set `WORK_DIR` to the chosen volume directory. These scripts are in the project root `scripts/` directory.

```bash
# Inspect high-confidence extra columns, missing columns, and missing rows; no writes.
python3 scripts/audit_shuowen_missing_frames.py "$WORK_DIR" \
  --start-page START --end-page END

# Add frames only to an explicitly confirmed grid column.
python3 scripts/frame_shuowen_volume.py "$WORK_DIR" \
  --start PAGE --end PAGE --columns GRID_COLUMN --apply

# Delete an explicitly confirmed false physical column.
python3 scripts/delete_page_column.py "$WORK_DIR" PAGE COLUMN

# Mandatory preflight for label refill. It proves radicals/components are not filtered,
# lists the only skipped continuation entries, and compares available labels to frame slots.
python3 scripts/check_resolved_shuowen_gloss_stream.py "$WORK_DIR" \
  --start-entry SOURCE_ENTRY --start-page START --end-page END

# Refill only labels from the verified zero-filter source, preserving all geometry.
python3 scripts/reflow_resolved_shuowen_glosses.py "$WORK_DIR" \
  --start-page START --end-page END --start-entry SOURCE_ENTRY --apply
```

Never use `fill_shuowen_labels_from_shidian.py` for a whole-range reflow: its
legacy text-quality filters can omit short component/radical entries. Use it only
for an explicitly reviewed one-off repair.

For a page whose boxes are correct columns but poor positions, use a fixed shared row baseline. Rebuild only that page’s `bbox` values and preserve each physical column’s label. Do not use a general re-detection pass that may reclassify existing seal columns as gloss columns.

## Final validation checklist

- Every frame column has exactly one label.
- No frame column is empty unless an unavoidable missing source label is explicitly recorded.
- No confirmed gloss slot retains seal frames.
- Every accepted missing-column candidate has visible large-glyph evidence.
- The audit records the source entry range, changed pages, backups, and any unresolved tail label.
