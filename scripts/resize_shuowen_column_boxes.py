#!/usr/bin/env python3
"""按固定尺寸调整《说文广义》一整列字框，保留中心、标签及序号。"""

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
    parser.add_argument("column", type=int)
    parser.add_argument("--width", type=float)
    parser.add_argument("--height", type=float)
    parser.add_argument("--scale-width", type=float,
                        help="按比例缩放现有宽度；例如 1.2 表示加宽 20%%")
    parser.add_argument("--scale-height", type=float,
                        help="按比例缩放现有高度；例如 1.05 表示加高 5%%")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    path = args.work_dir / ".debug" / f"fatie-{args.page:04d}" / "chars.json"
    items = json.loads(path.read_text())
    targets = [item for item in items if int(item.get("column", item.get("col", -1))) == args.column]
    if not targets:
        raise ValueError("目标列不存在")
    has_scale = args.scale_width is not None or args.scale_height is not None
    if not has_scale and (args.width is None or args.height is None):
        parser.error("请提供 --width/--height，或提供缩放比例")
    if has_scale and (args.width is not None or args.height is not None):
        parser.error("缩放比例不能与 --width/--height 同时使用")
    for item in targets:
        x1, y1, x2, y2 = item["bbox"]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        width = (x2 - x1) * (args.scale_width if args.scale_width is not None else 1.0) if has_scale else args.width
        height = (y2 - y1) * (args.scale_height if args.scale_height is not None else 1.0) if has_scale else args.height
        item["bbox"] = [cx - width / 2, cy - height / 2,
                        cx + width / 2, cy + height / 2]
    if args.apply:
        backup = path.parent / "backups"
        backup.mkdir(exist_ok=True)
        shutil.copy2(path, backup / f"chars-before-column-resize-{datetime.now():%Y%m%d-%H%M%S}.json")
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"page": args.page, "column": args.column, "frames": len(targets),
                      "width": args.width, "height": args.height, "scale_width": args.scale_width,
                      "scale_height": args.scale_height}, ensure_ascii=False))


if __name__ == "__main__":
    main()
