#!/usr/bin/env python3
"""按指定备份恢复一段页面的标签，保留当前框和坐标。"""

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
    parser.add_argument("--backup-name", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    changed: list[tuple[int, int]] = []
    for page in range(args.start, args.end + 1):
        page_dir = args.work_dir / ".debug" / f"fatie-{page:04d}"
        current_path = page_dir / "chars.json"
        backup_path = page_dir / "backups" / args.backup_name
        if not current_path.exists() or not backup_path.exists():
            continue
        current = json.loads(current_path.read_text())
        previous = json.loads(backup_path.read_text())
        if len(current) != len(previous):
            raise SystemExit(f"第 {page:04d} 页框数不同，拒绝恢复：{len(current)} != {len(previous)}")

        count = sum(1 for now, old in zip(current, previous) if now.get("char") != old.get("char"))
        if count:
            changed.append((page, count))
            if args.apply:
                backups = page_dir / "backups"
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                shutil.copy2(current_path, backups / f"chars-before-label-restore-{stamp}.json")
                for now, old in zip(current, previous):
                    now["char"] = old.get("char", "")
                current_path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n")

    action = "已恢复" if args.apply else "将恢复"
    print(f"{action} {len(changed)} 页、{sum(n for _, n in changed)} 个标签")
    print("pages=" + ",".join(f"{page:04d}:{count}" for page, count in changed))


if __name__ == "__main__":
    main()
