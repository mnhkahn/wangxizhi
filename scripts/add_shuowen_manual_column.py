#!/usr/bin/env python3
"""向已确认的页边篆书列补入固定字框，并在写前自动备份。"""

from __future__ import annotations

import argparse
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("page", type=int)
    parser.add_argument("column", type=int)
    parser.add_argument("--x", type=int, required=True, help="框左边界")
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--centers", required=True, help="字框纵向中心，逗号分隔")
    args = parser.parse_args()

    chars_path = args.work_dir / ".debug" / f"fatie-{args.page:04d}" / "chars.json"
    entries = json.loads(chars_path.read_text())
    if any(item.get("column") == args.column for item in entries):
        raise ValueError(f"page {args.page} 的 column={args.column} 已存在")
    centers = [int(value) for value in args.centers.split(",")]
    backup_dir = chars_path.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(chars_path, backup_dir / f"chars-before-manual-column-{stamp}.json")
    work_name = args.work_dir.name.removeprefix("程德洽-篆书-")
    for row, center in enumerate(centers):
        identifier = uuid.uuid4().hex
        entries.append({
            "id": identifier, "uuid": identifier, "char": "", "font": "篆书",
            "author": "程德洽", "work": work_name, "work_dir": str(args.work_dir),
            "bbox": [args.x, center - 64, args.x + args.width, center + 64],
            "column": args.column, "row": row, "visible": True,
        })
    chars_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")
    print(f"补入 {len(centers)} 个框：{chars_path}")


if __name__ == "__main__":
    main()
