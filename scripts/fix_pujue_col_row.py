#!/usr/bin/env python3
"""按当前 bbox 重新修正《普觉国师碑铭帖》的 column/row。

用途：人工调整过 char 和 bbox 后，旧的 column/row 可能没有跟着变。
本脚本以 chars.json 里的 char/bbox/id 为准，不重切图，不改字和框。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


DEFAULT_WORK_DIR = "王羲之-行书-普觉国师碑铭帖"


@dataclass
class CharRef:
    rec: dict
    center_x: float
    center_y: float
    width: float


def parse_page_spec(spec: str) -> list[str]:
    stems: list[str] = []
    seen: set[str] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            left, right = [p.strip() for p in part.split("-", 1)]
            start, end = int(left), int(right)
            if end < start:
                start, end = end, start
            names = [f"fatie-{i:03d}" for i in range(start, end + 1)]
        else:
            names = [f"fatie-{int(part):03d}" if part.isdigit() else part]
        for name in names:
            if name not in seen:
                stems.append(name)
                seen.add(name)
    return stems


def _char_ref(rec: dict) -> CharRef:
    bbox = rec.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise ValueError(f"无效 bbox: {bbox}")
    x1, y1, x2, y2 = [float(v) for v in bbox]
    return CharRef(
        rec=rec,
        center_x=(x1 + x2) / 2,
        center_y=(y1 + y2) / 2,
        width=max(1.0, x2 - x1),
    )


def group_chars_by_bbox(chars: list[dict]) -> list[list[dict]]:
    """按 bbox 横向位置分列，返回从右到左、列内从上到下的分组。"""
    refs = [_char_ref(rec) for rec in chars]
    if not refs:
        return []

    refs.sort(key=lambda item: item.center_x, reverse=True)
    median_width = sorted(item.width for item in refs)[len(refs) // 2]
    split_gap = max(120.0, median_width * 0.75)

    columns: list[list[CharRef]] = []
    current: list[CharRef] = [refs[0]]
    previous_x = refs[0].center_x
    for item in refs[1:]:
        if previous_x - item.center_x > split_gap:
            columns.append(current)
            current = [item]
        else:
            current.append(item)
        previous_x = item.center_x
    columns.append(current)

    columns.sort(key=lambda col: sum(item.center_x for item in col) / len(col), reverse=True)
    grouped: list[list[dict]] = []
    for col_idx, col in enumerate(columns):
        col.sort(key=lambda item: item.center_y)
        items = []
        for row_idx, item in enumerate(col):
            item.rec["column"] = col_idx
            item.rec["row"] = row_idx
            items.append(item.rec)
        grouped.append(items)
    return grouped


def _bbox_union(items: Iterable[dict]) -> list[float]:
    bboxes = [[float(v) for v in item["bbox"]] for item in items]
    return [
        min(b[0] for b in bboxes),
        min(b[1] for b in bboxes),
        max(b[2] for b in bboxes),
        max(b[3] for b in bboxes),
    ]


def rebuild_result(result_data: dict, grouped: list[list[dict]]) -> dict:
    parsed_results = []
    char_results = []
    recognized_text = ""
    global_index = 0

    for col_idx, items in enumerate(grouped):
        col_text = "".join(str(item.get("char", "")) for item in items)
        col_bbox = _bbox_union(items)
        recognized_text += col_text
        parsed_results.append(
            {
                "text": col_text,
                "bbox": col_bbox,
                "poly": [
                    [col_bbox[0], col_bbox[1]],
                    [col_bbox[2], col_bbox[1]],
                    [col_bbox[2], col_bbox[3]],
                    [col_bbox[0], col_bbox[3]],
                ],
            }
        )
        for row_idx, item in enumerate(items):
            char_results.append(
                {
                    "char": item.get("char", ""),
                    "bbox": [float(v) for v in item.get("bbox", [])],
                    "column": col_idx,
                    "row": row_idx,
                    "global_index": global_index,
                    "col_text": col_text,
                    "col_bbox": col_bbox,
                    "split_method": "manual_bbox_col_row_fix",
                }
            )
            global_index += 1

    result_data["recognized_text"] = recognized_text
    result_data["parsed_results"] = parsed_results
    result_data["char_results"] = char_results
    result_data["column_count"] = len(parsed_results)
    result_data["total_chars"] = len(char_results)
    result_data["timestamp"] = datetime.now().isoformat()
    return result_data


def sync_sqlite(project_root: Path, chars: list[dict]) -> int:
    sqlite_path = project_root / "ocr_output" / "glyphs.sqlite"
    if not sqlite_path.exists():
        return 0
    conn = sqlite3.connect(str(sqlite_path))
    try:
        rows = [
            (
                str(item.get("char", "")),
                str(item.get("work_dir", "")),
                str(item.get("author", "")),
                str(item.get("font", "")),
                str(item.get("work", "") or item.get("work_title", "")),
                str(item.get("id", "")),
            )
            for item in chars
            if item.get("id") and item.get("visible") is not False
        ]
        conn.executemany(
            """
            UPDATE glyphs
               SET char = ?, work_dir = ?, author = ?, font = ?, work_title = ?
             WHERE id = ?
            """,
            rows,
        )
        conn.commit()
        return conn.total_changes
    finally:
        conn.close()


def fix_page(project_root: Path, work_dir: Path, stem: str, no_sqlite: bool = False) -> tuple[str, int, str]:
    chars_path = work_dir / ".debug" / stem / "chars.json"
    result_path = work_dir / ".debug" / stem / "result.json"
    words_path = work_dir / "words" / f"{stem}.txt"
    if not chars_path.exists():
        raise FileNotFoundError(f"缺少 {chars_path}")

    chars = json.loads(chars_path.read_text(encoding="utf-8"))
    if not isinstance(chars, list):
        raise ValueError(f"{chars_path} 不是列表")

    grouped = group_chars_by_bbox(chars)
    ordered_chars = [item for col in grouped for item in col]
    text = "".join(str(item.get("char", "")) for item in ordered_chars)

    chars_path.write_text(json.dumps(ordered_chars, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result_path.exists():
        result_data = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        result_data = {}
    result_path.write_text(
        json.dumps(rebuild_result(result_data, grouped), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    words_path.parent.mkdir(parents=True, exist_ok=True)
    words_path.write_text(text, encoding="utf-8")

    sqlite_changes = 0 if no_sqlite else sync_sqlite(project_root, ordered_chars)
    return stem, len(ordered_chars), text if sqlite_changes == 0 else f"{text} sqlite_changes={sqlite_changes}"


def main() -> int:
    parser = argparse.ArgumentParser(description="修正《普觉国师碑铭帖》column/row")
    parser.add_argument("--work-dir", default=DEFAULT_WORK_DIR)
    parser.add_argument("--pages", default="000-006", help="页码，如 000-006 或 002,005")
    parser.add_argument("--no-sqlite", action="store_true")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    work_dir = Path(args.work_dir)
    if not work_dir.is_absolute():
        work_dir = project_root / work_dir

    failed = []
    for stem in parse_page_spec(args.pages):
        try:
            page, count, text = fix_page(project_root, work_dir, stem, no_sqlite=args.no_sqlite)
            print(f"OK {page} chars={count} text={text}")
        except Exception as exc:
            failed.append(f"{stem}: {exc}")
            print(f"FAIL {stem}: {exc}", file=sys.stderr)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
