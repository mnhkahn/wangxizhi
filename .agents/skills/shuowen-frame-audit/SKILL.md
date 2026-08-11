---
name: shuowen-frame-audit
description: Audit and safely repair boxed seal-script characters and Shidian gloss labels in this project’s Shuowen Guangyi volumes. Use when a user says a page has extra or missing frames, wrong column order, duplicated/missing gloss characters, asks to extract a consecutively deduplicated Shidian headword list, or asks to find suspect pages before modifying annotations.
---

# 说文广义框与释文审计

Use this skill for the project’s `程德洽-篆书-说文广义*` work directories. Treat a **physical column** as one character: every frame in that column must share one `char`.

## Non-negotiable rules

- Read page order from ascending page number and physical x coordinate from right to left. Do not trust historic `column` values as reading order.
- Separate three operations: frame existence, frame geometry, and gloss labels. Never silently combine them.
- Use downloaded Shidian glosses plus `shidian-gloss-resolutions.json` for labels. Do not OCR labels from the scan.
- The label stream is **zero-filter**: every valid one-character Shidian headword, including an independent radical/component, consumes one physical column. The only entries skipped are explicit `{"kind": "continuation"}` rules in `shidian-gloss-resolutions.json`.
- A physical column is one character slot: every frame in it must carry the **same single Unicode character**. Never concatenate repeated text, variants, or several source entries into one `char` field. Before and after any reflow, reject the write if a source item or a column label is not exactly one character; resolve it explicitly as a `headword` override or `continuation` rule first.
- Two physically adjacent columns on the same page must never carry the same label. When found, treat the later (leftward in reading order) source entry as a duplicated/continued source slot: add an explicit continuation rule, rebuild the source, and reflow from the earliest affected column through the volume end. Do not delete frames for this label-only repair.
- Do not change `bbox`, `row`, or `column` while only repairing `char` values.
- Before modifying, report candidates and wait for the user to confirm, unless they explicitly tell you to apply a specified repair.
- Back up `chars.json` before every write. Existing project scripts do this; preserve that behavior in new scripts.

## 提取纯释文字表（连续去重模式）

当用户只要一份按《史典古籍》原顺序排列的释文字表，并明确要求“连续相同的字只留一个”时：

- 永远保留原始 `shidian-glosses.json`，不要覆盖、不要修改其中的记录。
- 不得仅凭相邻 `headword` 相同而删除。两条都有完整释文时，它们是待校勘的独立槽位：保留槽位并输出 `unresolved_duplicate_headwords`，绝不静默丢字。
- 只有明确续行才能删除；把原始条目序号写入 `shidian-consecutive-dedup-exceptions.json` 的 `continuation_source_entries`。
- 已确认的独立重复字写入 `preserve_source_entries`；来源字头本身错误时，在 `headword_overrides` 以原始条目序号覆写。重新生成字表后从该锚点顺排到卷末，绝不只改当前页。
- 不在此模式中推断续文、偏旁或异体字，也不拿结果自动覆盖框上的 `char`。这是可核查的机械提取，不是校勘后的标准字表。
- 输出单独的 `shidian-headwords-consecutive-deduped.json`，并报告原记录数、删除的连续重复数和结果字数。
- 顺排前必须检查待校勘条目；存在未覆写的完整释文时拒绝顺排，要求先解析字头，而非删除它来凑数。

## Identify real problems

Recover the page’s vertical grid first. Classify every grid slot as seal script, gloss text, empty, or border/noise.

Classify a column as **certainly extra** only when its frames fall in a dense small-text (gloss) slot, or when its x position is one standard grid pitch from confirmed seal columns that are normally separated by a gloss slot. A short edge gap alone is not proof.

Classify a **missing column** only when an unboxed slot contains at least two large glyph regions matching the page’s seal-column width and row baseline. A missing frame within an existing column requires a matching unboxed glyph at a supported row baseline.

Use confirmed characters as anchors. Between two anchors, compare the source-label count with physical-column count. If the difference is `k`, accept a batch of missing-column candidates only when exactly `k` image-supported candidates occur in that interval. Do not infer missing columns from count alone.

## Safe workflow

1. Inspect only. Report page, physical position, expected character, and image evidence. Reject edge-only and border-only candidates.
2. After confirmation, add/delete only the named frame columns.
3. Run the label-stream preflight. It must show that component headwords are included and that the source/slot difference is understood.
4. Reflow labels once from the earliest changed page **through the volume's last annotated page** using the corrected Shidian source. Partial reflows are forbidden; do not hand-shift only part of a later range.
5. Verify: one non-empty label per physical column; no mixed labels in a column; source/slot difference is zero or explicitly recorded.
6. If a source entry is wrong, add an explicit `headword` or `continuation` rule to `shidian-gloss-resolutions.json`, then reflow from the affected page.

## Project commands

Set `WORK_DIR` to the chosen volume directory. These scripts are in the project root `scripts/` directory.

```bash
# Inspect high-confidence extra/missing columns and extra/missing frame rows; no writes.
python3 scripts/audit_shuowen_missing_frames.py "$WORK_DIR" \
  --start-page START --end-page END --output frame-audit.json

# After the user confirms the high-confidence whole-column candidates, apply only
# those additions/deletions. It never changes labels or any row-level frames.
python3 scripts/apply_shuowen_frame_audit.py "$WORK_DIR" frame-audit.json --apply

# Add frames only to an explicitly confirmed grid column.
python3 scripts/frame_shuowen_volume.py "$WORK_DIR" \
  --start PAGE --end PAGE --columns GRID_COLUMN --apply

# Delete an explicitly confirmed false physical column.
python3 scripts/delete_page_column.py "$WORK_DIR" PAGE COLUMN

# Mandatory preflight for label refill. It proves radicals/components are not filtered,
# lists the only skipped continuation entries, and compares available labels to frame slots.
python3 scripts/check_resolved_shuowen_gloss_stream.py "$WORK_DIR" \
  --start-entry SOURCE_ENTRY --start-page START --end-page END

# Build a separate, mechanically extracted headword list when the user explicitly
# requests adjacent-equal headwords to be deduplicated. It never alters the raw source.
python3 scripts/build_consecutive_deduped_shuowen_headwords.py "$WORK_DIR" \
  --output "$WORK_DIR/shidian-headwords-consecutive-deduped.json"

# Reflow from a user-confirmed physical-column anchor using that extracted
# list. It verifies the source is sufficient and refuses to introduce blank labels.
python3 scripts/reflow_consecutive_deduped_shuowen_headwords.py "$WORK_DIR" \
  --start-page PAGE --start-column COLUMN --anchor-char 字 --apply

# If the mechanically deduplicated source is shorter than the remaining physical
# columns, still reflow the verified prefix. The unresolved tail is preserved and
# recorded for later source repair; it is never silently blanked.
python3 scripts/reflow_consecutive_deduped_shuowen_headwords.py "$WORK_DIR" \
  --start-page PAGE --start-column COLUMN --anchor-char 字 \
  --preserve-tail --apply

# Insert a manually confirmed source-missing character and shift every later
# physical column through the volume end. Preserve the overflow in the pending file.
python3 scripts/reflow_column_label_stream.py "$WORK_DIR" \
  --start-page PAGE --end-page LAST_PAGE --page PAGE --column COLUMN \
  --insert 字 --stash-overflow --allow-page-duplicates --apply

# Refill only labels from the verified zero-filter source, preserving all geometry.
python3 scripts/reflow_resolved_shuowen_glosses.py "$WORK_DIR" \
  --start-page START --start-entry SOURCE_ENTRY --apply
```

Never use `fill_shuowen_labels_from_shidian.py` for a whole-range reflow: its
legacy text-quality filters can omit short component/radical entries. Use it only
for an explicitly reviewed one-off repair.

For a page whose boxes are correct columns but poor positions, use a fixed shared row baseline. Rebuild only that page’s `bbox` values and preserve each physical column’s label. Do not use a general re-detection pass that may reclassify existing seal columns as gloss columns.

## Final validation checklist

- Every frame column has exactly one label.
- Every frame column's non-empty labels form a singleton set, and that label has exactly one character.
- No adjacent physical columns on a page have the same label.
- No frame column is empty unless an unavoidable missing source label is explicitly recorded.
- No confirmed gloss slot retains seal frames.
- Every accepted missing-column candidate has visible large-glyph evidence.
- The audit records the source entry range, changed pages, backups, and any unresolved tail label.
