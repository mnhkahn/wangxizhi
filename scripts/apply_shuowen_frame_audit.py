#!/usr/bin/env python3
"""应用经确认的《说文广义》整列审计结果。

只处理 ``extra_columns`` 与 ``missing_columns``；绝不触碰行级候选或释文。
实际写入仍委托给已有的删列/补框脚本，因而每页会保留备份。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--min-confidence", type=float, default=0.90)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    report = json.loads(args.report.read_text())
    candidates = [*report.get("extra_columns", []), *report.get("missing_columns", [])]
    accepted = [item for item in candidates if item.get("confidence", 0) >= args.min_confidence]
    skipped = [item for item in candidates if item.get("confidence", 0) < args.min_confidence]
    extra = [item for item in accepted if item.get("kind") == "extra_column"]
    missing = [item for item in accepted if item.get("kind") == "missing_column"]

    root = Path(__file__).parent
    missing_by_page: dict[int, list[int]] = defaultdict(list)
    for item in missing:
        missing_by_page[int(item["page"])].append(int(item["grid_column"]))
    commands: list[list[str]] = []
    for item in extra:
        commands.append([
            sys.executable, str(root / "delete_page_column.py"), str(args.work_dir),
            str(item["page"]), str(item["stored_column"]),
        ])
    for page, columns in sorted(missing_by_page.items()):
        commands.append([
            sys.executable, str(root / "frame_shuowen_volume.py"), str(args.work_dir),
            "--start", str(page), "--end", str(page), "--columns",
            ",".join(map(str, sorted(set(columns)))), "--apply",
        ])
    print(json.dumps({
        "extra_columns_to_delete": len(extra),
        "missing_columns_to_add": len(missing),
        "skipped_low_confidence": skipped,
        "commands": [" ".join(command) for command in commands],
    }, ensure_ascii=False, indent=2))
    if not args.apply:
        return
    for command in commands:
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
