#!/usr/bin/env python3
"""删除某页的整列字框，并保留可恢复的 chars.json 备份。"""

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
    args = parser.parse_args()
    path = args.work_dir / ".debug" / f"fatie-{args.page:04d}" / "chars.json"
    items = json.loads(path.read_text())
    kept = [item for item in items if int(item["column"]) != args.column]
    removed = len(items) - len(kept)
    if not removed:
        raise ValueError("目标列不存在")
    backup = path.parent / "backups"
    backup.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, backup / f"chars-before-column-delete-{stamp}.json")
    path.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n")
    print(f"删除 {removed} 个框")


if __name__ == "__main__":
    main()
