#!/usr/bin/env python3
"""保留指定列并规范页内 column 编号，不改变任何 bbox 或 char。"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


def parse_map(value: str) -> dict[int, int]:
    result: dict[int, int] = {}
    for pair in value.split(","):
        old, new = pair.split(":", 1)
        result[int(old)] = int(new)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("page", type=int)
    parser.add_argument("--map", required=True, dest="column_map")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    mapping = parse_map(args.column_map)
    path = args.work_dir / ".debug" / f"fatie-{args.page:04d}" / "chars.json"
    items = json.loads(path.read_text())
    kept = []
    for item in items:
        old = int(item.get("column", item.get("col", -1)))
        if old not in mapping:
            continue
        item = dict(item)
        item["column"] = mapping[old]
        kept.append(item)
    if not kept:
        raise ValueError("映射后没有保留任何框")
    for column in sorted({item["column"] for item in kept}):
        members = sorted((item for item in kept if item["column"] == column),
                         key=lambda item: (item["bbox"][1] + item["bbox"][3]) / 2)
        for row, item in enumerate(members):
            item["row"] = row
    kept.sort(key=lambda item: (-item["column"], item["row"]))
    if args.apply:
        backup = path.parent / "backups"
        backup.mkdir(exist_ok=True)
        shutil.copy2(path, backup / f"chars-before-column-relabel-{datetime.now():%Y%m%d-%H%M%S}.json")
        path.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"page": args.page, "kept_frames": len(kept), "columns": sorted(set(mapping.values()))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
