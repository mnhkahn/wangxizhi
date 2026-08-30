#!/usr/bin/env python3
"""按物理列顺序，用已审核的候选释文字流填充指定页面。

只改 char；不改 bbox、row、column。每次写入均备份原 chars.json。
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


def page_slots(work_dir: Path, start_page: int, end_page: int) -> tuple[dict[int, tuple[Path, list[dict]]], list[tuple[int, int]]]:
    pages: dict[int, tuple[Path, list[dict]]] = {}
    slots: list[tuple[int, int]] = []
    for page in range(start_page, end_page + 1):
        path = work_dir / ".debug" / f"fatie-{page:04d}" / "chars.json"
        if not path.exists():
            continue
        items = json.loads(path.read_text(encoding="utf-8"))
        columns: dict[int, list[dict]] = {}
        for item in items:
            column = item.get("column", item.get("col"))
            if isinstance(column, int):
                columns.setdefault(column, []).append(item)

        def centre(group: list[dict]) -> float:
            return sum((entry["bbox"][0] + entry["bbox"][2]) / 2 for entry in group) / len(group)

        slots.extend(
            (page, column)
            for column, group in sorted(columns.items(), key=lambda pair: centre(pair[1]), reverse=True)
        )
        pages[page] = (path, items)
    return pages, slots


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start-page", type=int, required=True)
    parser.add_argument("--end-page", type=int, required=True)
    parser.add_argument("--start-entry", type=int, default=1, help="候选流的 1-based 起点")
    parser.add_argument("--start-column", type=int,
                        help="从起始页的指定物理列开始；省略则从该页最右列开始")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    source = args.source or args.work_dir / "shuowen-reference-candidates-adjacent-deduped.json"
    candidates = json.loads(source.read_text(encoding="utf-8"))["entries"]
    labels = [entry["candidate"]["char"] for entry in candidates]
    if any(not isinstance(char, str) or len(char) != 1 for char in labels):
        raise ValueError("候选流含非单字标签，拒绝写入")

    pages, slots = page_slots(args.work_dir, args.start_page, args.end_page)
    if args.start_column is not None:
        try:
            first = slots.index((args.start_page, args.start_column))
        except ValueError as error:
            raise ValueError(f"第 {args.start_page:04d} 页不存在列 {args.start_column}") from error
        slots = slots[first:]
    begin = args.start_entry - 1
    assigned = labels[begin:begin + len(slots)]
    if len(assigned) != len(slots):
        raise ValueError(f"候选释文不足：需 {len(slots)}，可用 {len(assigned)}")
    if any(assigned[index] == assigned[index + 1] for index in range(len(assigned) - 1)):
        raise ValueError("候选流仍有相邻重复，拒绝写入")

    audit = {
        "source": str(source),
        "pages": [args.start_page, args.end_page],
        "physical_columns": len(slots),
        "candidate_entries": [args.start_entry, args.start_entry + len(slots) - 1],
        "first": {"slot": slots[0], "char": assigned[0]},
        "last": {"slot": slots[-1], "char": assigned[-1]},
    }
    print(json.dumps(audit, ensure_ascii=False))
    if not args.apply:
        return

    for (page, column), char in zip(slots, assigned):
        _, items = pages[page]
        for item in items:
            if item.get("column", item.get("col")) == column:
                item["char"] = char

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path, items in pages.values():
        backup = path.parent / "backups"
        backup.mkdir(exist_ok=True)
        shutil.copy2(path, backup / f"chars-before-candidate-label-reflow-{stamp}.json")
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit_path = args.work_dir / f"candidate-label-reflow-{args.start_page:04d}-{args.end_page:04d}.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入；审计：{audit_path}")


if __name__ == "__main__":
    main()
