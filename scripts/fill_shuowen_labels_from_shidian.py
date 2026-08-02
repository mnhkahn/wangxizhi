#!/usr/bin/env python3
"""按《史典古籍》释文顺序为《说文广义》的篆书列填字。

只更新空列的 ``char``，不会改 bbox、column、row 或人工已有的字；每页
写入前都会在 ``backups/`` 留一份原始 chars.json，并输出可复核的对应清单。
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from propagate_seal_column_labels import column_groups


def usable_entries(path: Path) -> list[dict]:
    """过滤史典 OCR 产生的续行和明显损坏的伪词条。"""
    data = json.loads(path.read_text())
    return [
        entry for entry in data["entries"]
        if len(str(entry.get("headword", ""))) == 1 and "从" in str(entry.get("gloss", ""))
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start-page", type=int, required=True)
    parser.add_argument("--end-page", type=int, required=True)
    parser.add_argument("--start-source", type=int, required=True, help="清洗后来源的 1 起始条目")
    parser.add_argument("--source", type=Path, help="默认读取字帖目录下的 shidian-glosses.json")
    parser.add_argument("--overwrite", action="store_true", help="重写已有字；用于修正已知来源偏移")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    source = args.source or args.work_dir / "shidian-glosses.json"
    entries = usable_entries(source)
    offset = args.start_source - 1
    assignments: list[dict] = []
    cursor = offset
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    for page in range(args.start_page, args.end_page + 1):
        debug = args.work_dir / ".debug" / f"fatie-{page:04d}"
        chars_path = debug / "chars.json"
        if not chars_path.exists():
            continue
        chars = json.loads(chars_path.read_text())
        groups = column_groups(chars, 180) if chars else []
        changed = False
        for column, group in enumerate(groups):
            if cursor >= len(entries):
                raise RuntimeError("来源释文不足，已停止写入")
            entry = entries[cursor]
            label = str(entry["headword"])
            existing = {str(item.get("char", "")).strip() for item in group} - {""}
            if not existing or args.overwrite:
                for item in group:
                    item["char"] = label
                changed = True
            assignments.append({
                "page": page,
                "column": column,
                "char": label,
                "source_index": cursor + 1,
                "headword_line_id": entry.get("headword_line_id"),
                "kept_existing": bool(existing),
            })
            cursor += 1
        if args.apply and changed:
            backups = debug / "backups"
            backups.mkdir(exist_ok=True)
            shutil.copy2(chars_path, backups / f"chars-before-shidian-labels-{stamp}.json")
            chars_path.write_text(json.dumps(chars, ensure_ascii=False, indent=2) + "\n")

    audit = {
        "source": str(source),
        "start_source": args.start_source,
        "next_source": cursor + 1,
        "assignments": assignments,
    }
    audit_path = args.work_dir / f"shidian-labels-{args.start_page:04d}-{args.end_page:04d}.json"
    if args.apply:
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(f"列数：{len(assignments)}；来源 {args.start_source}..{cursor}；审计：{audit_path}")


if __name__ == "__main__":
    main()
