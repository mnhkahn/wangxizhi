#!/usr/bin/env python3
"""删除误框列，并把该列释文连续承接到后续真实列。

只删除指定列的框，其余框坐标、行列号保持不变。释文按实际 x 坐标右至左
组成全页流：删除一个槽位后，该槽位原有的字进入下一真实槽，后续字跨页顺排。
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


def columns(items):
    grouped = {}
    for item in items:
        col = item.get("column", item.get("col"))
        if isinstance(col, int):
            grouped.setdefault(col, []).append(item)

    def centre(group):
        return sum((x["bbox"][0] + x["bbox"][2]) / 2 for x in group) / len(group)

    return sorted(grouped.items(), key=lambda item: centre(item[1]), reverse=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("page", type=int)
    parser.add_argument("column", type=int)
    parser.add_argument("--end-page", type=int, required=True)
    parser.add_argument("--stash-overflow", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    pages, slots, old_labels = {}, [], []
    for page in range(args.page, args.end_page + 1):
        path = args.work_dir / ".debug" / f"fatie-{page:04d}" / "chars.json"
        if not path.exists():
            continue
        items = json.loads(path.read_text())
        pages[page] = [path, items]
        for col, group in columns(items):
            values = {str(x.get("char", "")).strip() for x in group}
            values.discard("")
            if len(values) > 1:
                raise ValueError(f"{page:04d}/col={col} 同列释文不一致：{sorted(values)}")
            slots.append((page, col))
            old_labels.append(next(iter(values), ""))
    try:
        index = slots.index((args.page, args.column))
    except ValueError as error:
        raise ValueError("目标列不存在") from error
    carried = old_labels[index]
    overflow = old_labels[-1]
    if overflow and not args.stash_overflow:
        raise ValueError(f"末尾字「{overflow}」会溢出；请加 --stash-overflow")

    # 先在内存删除框，再以旧字流（去掉末尾）写回剩余槽位。
    path, items = pages[args.page]
    pages[args.page][1] = [
        item for item in items if item.get("column", item.get("col")) != args.column
    ]
    new_slots = []
    for page, (_, page_items) in pages.items():
        for col, _ in columns(page_items):
            new_slots.append((page, col))
    if len(new_slots) != len(old_labels) - 1:
        raise RuntimeError("列流长度异常，未写入")
    new_labels = old_labels[:-1]
    audit = {
        "operation": "remove_column_and_carry_label",
        "page": args.page,
        "column": args.column,
        "carried_label": carried,
        "overflow": overflow or None,
        "slots_before": len(old_labels),
        "slots_after": len(new_slots),
    }
    print(json.dumps(audit, ensure_ascii=False))
    if not args.apply:
        return

    for (page, col), label in zip(new_slots, new_labels):
        _, page_items = pages[page]
        for item in page_items:
            if item.get("column", item.get("col")) == col:
                item["char"] = label
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if overflow:
        stash_path = args.work_dir / "pending-overflow-labels.json"
        stash = json.loads(stash_path.read_text()) if stash_path.exists() else []
        stash.insert(0, {"char": overflow, "operation": audit["operation"], "at": stamp})
        stash_path.write_text(json.dumps(stash, ensure_ascii=False, indent=2) + chr(10))
    for path, page_items in pages.values():
        backup = path.parent / "backups"
        backup.mkdir(exist_ok=True)
        shutil.copy2(path, backup / f"chars-before-carry-delete-{stamp}.json")
        path.write_text(json.dumps(page_items, ensure_ascii=False, indent=2) + chr(10))
    audit_path = args.work_dir / f"column-carry-delete-{args.page:04d}-{args.column}.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + chr(10))
    print(f"已写入；审计：{audit_path}")


if __name__ == "__main__":
    main()
