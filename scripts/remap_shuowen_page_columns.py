#!/usr/bin/env python3
"""安全重映射单页《说文广义》字框列号，不触碰框、行号或释文。"""

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
    parser.add_argument("--map", required=True, dest="mapping", help="例如 3:4,1:2")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    mapping = {int(pair.split(":", 1)[0]): int(pair.split(":", 1)[1])
               for pair in args.mapping.split(",")}
    path = args.work_dir / ".debug" / f"fatie-{args.page:04d}" / "chars.json"
    items = json.loads(path.read_text())
    found = {item.get("column", item.get("col")) for item in items}
    missing = set(mapping) - found
    if missing:
        raise ValueError(f"目标旧列不存在：{sorted(missing)}")
    targets = list(mapping.values())
    if len(set(targets)) != len(targets):
        raise ValueError("新列号不能重复")
    print({"page": args.page, "mapping": mapping, "frames": sum(item.get("column", item.get("col")) in mapping for item in items)})
    if not args.apply:
        return
    backup = path.parent / "backups"
    backup.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, backup / f"chars-before-column-remap-{stamp}.json")
    for item in items:
        old = item.get("column", item.get("col"))
        if old in mapping:
            item["column"] = mapping[old]
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
