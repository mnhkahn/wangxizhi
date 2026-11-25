#!/usr/bin/env python3
"""安全地为一个已确认的物理列写入单个释文字头。

只修改 ``char``，保留 bbox、row、column；写入前自动备份 chars.json。
"""

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
    parser.add_argument("char", nargs="?")
    parser.add_argument("--clear", action="store_true", help="仅清空该列标签，保留框和坐标")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.clear == (args.char is not None):
        raise SystemExit("必须二选一：传入一个 char，或使用 --clear")
    if args.char is not None and len(args.char) != 1:
        raise SystemExit("char 必须恰好是一个 Unicode 字符")
    path = args.work_dir / ".debug" / f"fatie-{args.page:04d}" / "chars.json"
    data = json.loads(path.read_text())
    matched = [item for item in data if int(item.get("column", -1)) == args.column]
    if not matched:
        raise SystemExit(f"第 {args.page:04d} 页不存在 column={args.column}")
    before = sorted({str(item.get("char", "")) for item in matched})
    target = "" if args.clear else args.char
    print(json.dumps({"page": args.page, "column": args.column, "frames": len(matched), "before": before, "after": target}, ensure_ascii=False))
    if not args.apply:
        return
    backup = args.work_dir / ".debug" / "backups"
    backup.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, backup / f"chars-before-label-{args.page:04d}-col{args.column}-{stamp}.json")
    for item in matched:
        item["char"] = target
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
