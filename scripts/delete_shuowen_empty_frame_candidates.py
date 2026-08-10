#!/usr/bin/env python3
"""删除由像素空框审计确认的单框，并为每页创建备份。"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("audit", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    candidates = json.loads(args.audit.read_text()).get("candidates", [])
    targets: dict[int, set[tuple[int, int, tuple[int, int, int, int]]]] = defaultdict(set)
    for item in candidates:
        page = int(item["page"])
        targets[page].add((
            int(item["entry_index"]),
            int(item.get("column", -1)),
            tuple(map(int, item["bbox"])),
        ))

    removed: list[dict] = []
    planned = 0
    pages: dict[int, tuple[Path, list[dict], list[dict]]] = {}
    for page, page_targets in targets.items():
        path = args.work_dir / ".debug" / f"fatie-{page:04d}" / "chars.json"
        items = json.loads(path.read_text())
        kept = []
        found = set()
        for index, item in enumerate(items):
            column = int(item.get("column", item.get("col", -1)))
            bbox = tuple(map(int, item.get("bbox", [])))
            key = (index, column, bbox)
            if key in page_targets:
                removed.append({"page": page, "column": column, "row": item.get("row"), "char": item.get("char", ""), "bbox": list(bbox)})
                found.add(key)
            else:
                kept.append(item)
        missing = page_targets - found
        if missing:
            raise ValueError(f"第 {page:04d} 页候选已变化，拒绝删除：{sorted(missing)}")
        planned += len(found)
        pages[page] = (path, items, kept)

    print(f"将删除 {planned} 个空框候选，涉及 {len(pages)} 页")
    if not args.apply:
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path, _, kept in pages.values():
        backup = path.parent / "backups"
        backup.mkdir(exist_ok=True)
        shutil.copy2(path, backup / f"chars-before-empty-frame-delete-{stamp}.json")
        path.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n")
    output = args.work_dir / f"empty-frame-delete-{stamp}.json"
    output.write_text(json.dumps({"audit": str(args.audit), "removed": removed}, ensure_ascii=False, indent=2) + "\n")
    print(f"已删除 {planned} 个框；审计：{output}")


if __name__ == "__main__":
    main()
