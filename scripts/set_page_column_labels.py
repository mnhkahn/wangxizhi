#!/usr/bin/env python3
"""只按页面从右至左的列顺序写入篆书释文，不改框或坐标。"""

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
    parser.add_argument("labels", help="从右至左的列字，以英文逗号分隔")
    args = parser.parse_args()

    chars_path = args.work_dir / ".debug" / f"fatie-{args.page:04d}" / "chars.json"
    chars = json.loads(chars_path.read_text())
    groups: dict[int, list[dict]] = {}
    for item in chars:
        groups.setdefault(int(item["column"]), []).append(item)
    columns = sorted(groups, reverse=True)
    labels = args.labels.split(",")
    if len(columns) != len(labels):
        raise ValueError(f"页面有 {len(columns)} 列，传入了 {len(labels)} 个列字")

    backup_dir = chars_path.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(chars_path, backup_dir / f"chars-before-manual-labels-{stamp}.json")
    for column, label in zip(columns, labels):
        for item in groups[column]:
            item["char"] = label
    chars_path.write_text(json.dumps(chars, ensure_ascii=False, indent=2) + "\n")
    print("；".join(f"col={column}: {label}" for column, label in zip(columns, labels)))


if __name__ == "__main__":
    main()
