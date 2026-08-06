#!/usr/bin/env python3
"""备份并清空《说文广义》指定页范围内的 chars.json。"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument(
        "--columns",
        help="只删除指定列号，逗号分隔；省略时清空整页",
    )
    args = parser.parse_args()
    selected_columns = (
        {int(value) for value in args.columns.split(",")}
        if args.columns else None
    )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    cleared_pages = 0
    cleared_frames = 0
    for number in range(args.start, args.end + 1):
        debug = args.work_dir / ".debug" / f"fatie-{number:04d}"
        chars = debug / "chars.json"
        if not chars.exists():
            continue
        entries = json.loads(chars.read_text())
        backups = debug / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        shutil.copy2(chars, backups / f"chars-before-clear-{stamp}.json")
        kept = (
            [item for item in entries if int(item.get("column", item.get("col", -1))) not in selected_columns]
            if selected_columns is not None else []
        )
        chars.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n")
        cleared_pages += 1
        cleared_frames += len(entries) - len(kept)
    action = "删除" if selected_columns is not None else "清空"
    print(f"{action} {cleared_pages} 页，共 {cleared_frames} 个框")


if __name__ == "__main__":
    main()
