#!/usr/bin/env python3
"""按原始释文字头顺序重排《说文广义》列字。

逐条消费 shidian-glosses.json 的原始 entries，保留重复与短条目。
只写 char，绝不改字框、列号或坐标。
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


def column_groups(items: list[dict]) -> list[list[dict]]:
    groups: dict[int, list[dict]] = {}
    for item in items:
        column = item.get("column", item.get("col"))
        if isinstance(column, int):
            groups.setdefault(column, []).append(item)

    def center(group: list[dict]) -> float:
        return sum((item["bbox"][0] + item["bbox"][2]) / 2 for item in group) / len(group)

    return sorted(groups.values(), key=center, reverse=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start-page", type=int, required=True)
    parser.add_argument("--end-page", type=int, required=True)
    parser.add_argument("--start-source", type=int, required=True, help="原始 entries 的 1 起始序号")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    source_path = args.work_dir / "shidian-glosses.json"
    source = json.loads(source_path.read_text())["entries"]
    labels = [str(item.get("headword", "")).strip() for item in source]
    if any(len(label) != 1 for label in labels):
        raise ValueError("原始释文存在非单字字头，拒绝写入")

    cursor = args.start_source - 1
    assignments: list[dict] = []
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    pending_writes: list[tuple[Path, list[dict]]] = []

    for page in range(args.start_page, args.end_page + 1):
        chars_path = args.work_dir / ".debug" / f"fatie-{page:04d}" / "chars.json"
        if not chars_path.exists():
            continue
        chars = json.loads(chars_path.read_text())
        groups = column_groups(chars)
        if cursor + len(groups) > len(labels):
            raise RuntimeError(
                f"来源释文不足：第 {page:04d} 页需要 {len(groups)} 条，"
                f"仅剩 {len(labels) - cursor} 条；未写入任何文件"
            )
        for group in groups:
            label = labels[cursor]
            for item in group:
                item["char"] = label
            assignments.append(
                {
                    "page": page,
                    "column": int(group[0].get("column", group[0].get("col"))),
                    "char": label,
                    "source_index": cursor + 1,
                }
            )
            cursor += 1
        pending_writes.append((chars_path, chars))

    audit = {
        "source": str(source_path),
        "mode": "raw_entries",
        "start_source": args.start_source,
        "next_source": cursor + 1,
        "assignments": assignments,
    }
    if args.apply:
        for chars_path, chars in pending_writes:
            backups = chars_path.parent / "backups"
            backups.mkdir(exist_ok=True)
            shutil.copy2(chars_path, backups / f"chars-before-raw-gloss-reflow-{stamp}.json")
            chars_path.write_text(json.dumps(chars, ensure_ascii=False, indent=2) + "\n")
        audit_path = args.work_dir / (
            f"raw-gloss-reflow-{args.start_page:04d}-{args.end_page:04d}.json"
        )
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
        print(f"重排 {len(assignments)} 列；来源 {args.start_source}..{cursor}；审计：{audit_path}")
    else:
        print(f"预览 {len(assignments)} 列；来源 {args.start_source}..{cursor}")


if __name__ == "__main__":
    main()
