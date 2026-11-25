#!/usr/bin/env python3
"""删除框审计确认的列内冗余框；不会改释文、列号或其他坐标。"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def frame_center_y(item: dict) -> int:
    """返回与审计报告一致的四舍五入纵向中心。"""
    bbox = item["bbox"]
    return round((float(bbox[1]) + float(bbox[3])) / 2)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="删除 audit_shuowen_missing_frames.py 报告中的 extra_rows（先备份）"
    )
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("audit", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    report = json.loads(args.audit.read_text())
    requested: dict[int, set[tuple[int, int]]] = defaultdict(set)
    for candidate in report.get("extra_rows", []):
        requested[int(candidate["page"])].add(
            (int(candidate["stored_column"]), int(candidate["y"]))
        )

    planned: dict[int, tuple[Path, list[dict], list[dict], list[dict]]] = {}
    for page, targets in requested.items():
        path = args.work_dir / ".debug" / f"fatie-{page:04d}" / "chars.json"
        items = json.loads(path.read_text())
        matched_indexes: set[int] = set()
        removed: list[dict] = []
        for column, y in targets:
            matches = [
                i for i, item in enumerate(items)
                if int(item.get("column", item.get("col", -1))) == column
                and frame_center_y(item) == y
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"第 {page:04d} 页 c{column} y={y} 候选已变化或不唯一：{matches}"
                )
            index = matches[0]
            if index in matched_indexes:
                raise ValueError(f"第 {page:04d} 页同一框被重复命中：index={index}")
            matched_indexes.add(index)
            item = items[index]
            removed.append({
                "page": page,
                "column": column,
                "row": item.get("row"),
                "char": item.get("char", ""),
                "bbox": item["bbox"],
            })
        kept = [item for i, item in enumerate(items) if i not in matched_indexes]
        planned[page] = (path, items, kept, removed)

    count = sum(len(x[3]) for x in planned.values())
    print(f"将删除 {count} 个列内冗余框，涉及 {len(planned)} 页")
    if not args.apply:
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    manifest: list[dict] = []
    for path, _items, kept, removed in planned.values():
        backup = path.parent / "backups"
        backup.mkdir(exist_ok=True)
        shutil.copy2(path, backup / f"chars-before-extra-row-delete-{stamp}.json")
        path.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n")
        manifest.extend(removed)
    output = args.work_dir / f"extra-row-delete-{stamp}.json"
    output.write_text(json.dumps({"audit": str(args.audit), "removed": manifest}, ensure_ascii=False, indent=2) + "\n")
    print(f"已删除 {count} 个框；审计：{output}")


if __name__ == "__main__":
    main()
