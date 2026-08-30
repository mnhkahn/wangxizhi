#!/usr/bin/env python3
"""消除同页两个字框的几何重叠，不改变标签、列或行。"""

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
    parser.add_argument("left_index", type=int)
    parser.add_argument("right_index", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    path = args.work_dir / ".debug" / f"fatie-{args.page:04d}" / "chars.json"
    entries = json.loads(path.read_text())
    first, second = entries[args.left_index], entries[args.right_index]
    a, b = list(first["bbox"]), list(second["bbox"])
    overlap_x = min(a[2], b[2]) - max(a[0], b[0])
    overlap_y = min(a[3], b[3]) - max(a[1], b[1])
    if overlap_x <= 0 or overlap_y <= 0:
        raise ValueError("目标框并未重叠")
    if overlap_y <= overlap_x:
        upper, lower = sorted((first, second), key=lambda item: (item["bbox"][1] + item["bbox"][3]) / 2)
        boundary = round((upper["bbox"][3] + lower["bbox"][1]) / 2, 2)
        upper["bbox"][3] = boundary
        lower["bbox"][1] = boundary
        axis = "y"
    else:
        left, right = sorted((first, second), key=lambda item: (item["bbox"][0] + item["bbox"][2]) / 2)
        boundary = round((left["bbox"][2] + right["bbox"][0]) / 2, 2)
        left["bbox"][2] = boundary
        right["bbox"][0] = boundary
        axis = "x"
    if args.apply:
        backup = path.parent / "backups"
        backup.mkdir(exist_ok=True)
        shutil.copy2(path, backup / f"chars-before-overlap-resolve-{datetime.now():%Y%m%d-%H%M%S}.json")
        path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"page": args.page, "entries": [args.left_index, args.right_index], "axis": axis}, ensure_ascii=False))


if __name__ == "__main__":
    main()
