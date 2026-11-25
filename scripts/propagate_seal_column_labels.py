#!/usr/bin/env python3
"""按框的 x 坐标重建篆字物理列，并传播每列最上方的释文。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def column_groups(entries: list[dict], tolerance: float) -> list[list[dict]]:
    """按框中心 x 聚类；返回值由右至左排列。"""
    groups: list[list[dict]] = []
    for entry in sorted(entries, key=lambda item: (item["bbox"][0] + item["bbox"][2]) / 2):
        center = (entry["bbox"][0] + entry["bbox"][2]) / 2
        if groups:
            reference = sum((item["bbox"][0] + item["bbox"][2]) / 2 for item in groups[-1]) / len(groups[-1])
            if abs(center - reference) <= tolerance:
                groups[-1].append(entry)
                continue
        groups.append([entry])
    return list(reversed(groups))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("chars_json", type=Path)
    parser.add_argument("--tolerance", type=float, default=180)
    parser.add_argument("--column-start", type=int, default=0, help="最右物理列的编号")
    parser.add_argument(
        "--label", action="append", default=[], metavar="列号:释文",
        help="指定列的释文，优先于框内已有值；可重复使用",
    )
    parser.add_argument(
        "--clear-label", type=int, action="append", default=[], metavar="列号",
        help="清空指定物理列的释文；可重复使用",
    )
    parser.add_argument("--leftmost", type=int, help="仅处理最左侧 N 条物理列")
    parser.add_argument("--only-column", type=int, action="append", help="仅处理指定的重算列号；可重复")
    parser.add_argument("--labels-only", action="store_true", help="只复制释文，不改行列号")
    parser.add_argument("--keep-rows", action="store_true", help="更新列号但保留现有行号")
    parser.add_argument("--indices-only", action="store_true", help="只重排行列号，不复制释文")
    args = parser.parse_args()

    entries = json.loads(args.chars_json.read_text())
    overrides = {}
    for value in args.label:
        column_text, separator, label = value.partition(":")
        if not separator or not column_text.isdigit() or not label:
            raise ValueError(f"无效的 --label：{value}（应为 列号:释文）")
        overrides[int(column_text)] = label
    clear_labels = set(args.clear_label)
    groups = column_groups(entries, args.tolerance)
    selected = set(range(len(groups)))
    if args.leftmost is not None:
        selected = set(range(max(0, len(groups) - args.leftmost), len(groups)))
    if args.only_column:
        selected = {
            offset for offset in range(len(groups))
            if args.column_start + offset in set(args.only_column)
        }
    for offset, group in enumerate(groups):
        column = args.column_start + offset
        if offset not in selected:
            continue
        ordered = sorted(group, key=lambda item: item["bbox"][1])
        label = overrides.get(column) or next(
            (str(item.get("char", "")).strip() for item in ordered if str(item.get("char", "")).strip()), ""
        )
        for row, item in enumerate(ordered):
            if not args.labels_only:
                item["column"] = column
                if not args.keep_rows:
                    item["row"] = row
            if column in clear_labels and not args.indices_only:
                item["char"] = ""
            elif label and not args.indices_only:
                item["char"] = label
        print(f"列 {column}: {len(ordered)} 框，释文「{label}」")
    args.chars_json.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
