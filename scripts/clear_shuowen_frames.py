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
    args = parser.parse_args()

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
        chars.write_text("[]\n")
        cleared_pages += 1
        cleared_frames += len(entries)
    print(f"清空 {cleared_pages} 页，共 {cleared_frames} 个框")


if __name__ == "__main__":
    main()
