#!/usr/bin/env python3
"""按单页内每个物理列的纵向坐标连续重编号 row。"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("page", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    path = args.work_dir / ".debug" / f"fatie-{args.page:04d}" / "chars.json"
    items = json.loads(path.read_text())
    columns: dict[int, list[dict]] = {}
    for item in items:
        column = item.get("column", item.get("col"))
        if not isinstance(column, int):
            raise ValueError("存在缺少整数 column 的框")
        columns.setdefault(column, []).append(item)
    changes = []
    for column, members in columns.items():
        for row, item in enumerate(sorted(members, key=lambda value: (value["bbox"][1] + value["bbox"][3]) / 2)):
            if item.get("row") != row:
                changes.append({"column": column, "from": item.get("row"), "to": row, "bbox": item["bbox"]})
                item["row"] = row
    print(json.dumps({"page": args.page, "row_changes": changes}, ensure_ascii=False))
    if not args.apply:
        return
    backup = path.parent / "backups"
    backup.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, backup / f"chars-before-row-renumber-{stamp}.json")
    items.sort(key=lambda item: (-item["column"], item["row"]))
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
