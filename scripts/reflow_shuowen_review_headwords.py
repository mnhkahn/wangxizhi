#!/usr/bin/env python3
"""把本地字头流按物理列顺序写入，供人工校对未解析 OCR 项。"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


def page_slots(work_dir: Path, start: int, end: int):
    slots, pages = [], {}
    for page in range(start, end + 1):
        path = work_dir / ".debug" / f"fatie-{page:04d}" / "chars.json"
        if not path.exists():
            continue
        items = json.loads(path.read_text())
        groups: dict[int, list[dict]] = {}
        for item in items:
            col = item.get("column", item.get("col"))
            if isinstance(col, int):
                groups.setdefault(col, []).append(item)
        for col, group in sorted(groups.items(), key=lambda pair: sum((x["bbox"][0] + x["bbox"][2]) / 2 for x in pair[1]) / len(pair[1]), reverse=True):
            slots.append((page, col))
        pages[page] = (path, items)
    return slots, pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--start-page", type=int, required=True)
    parser.add_argument("--start-column", type=int, required=True)
    parser.add_argument("--end-page", type=int, required=True)
    parser.add_argument("--coerce-first-char", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    source = json.loads(args.source.read_text())["headwords"]
    labels = []
    provisional = []
    for entry in source:
        text = str(entry.get("char", ""))
        if len(text) != 1:
            if not args.coerce_first_char or not text:
                raise ValueError(f"来源第 {entry.get('source_entry')} 条不是单字")
            provisional.append({"source_entry": entry.get("source_entry"), "raw": text, "char": text[0]})
            text = text[0]
        labels.append({"source_entry": entry.get("source_entry"), "char": text})
    slots, pages = page_slots(args.work_dir, args.start_page, args.end_page)
    start_at = slots.index((args.start_page, args.start_column))
    slots = slots[start_at:]
    if len(labels) < len(slots):
        raise ValueError(f"来源只有 {len(labels)} 字，框有 {len(slots)} 列")
    assignments = [{"page": page, "column": col, **label} for (page, col), label in zip(slots, labels)]
    audit = {"source": str(args.source), "slots": len(slots), "source_labels": len(labels),
             "unused_source": labels[len(slots):], "provisional_multichar": provisional,
             "assignments": assignments}
    print(json.dumps({k: v for k, v in audit.items() if k != "assignments"}, ensure_ascii=False))
    if not args.apply:
        return
    for assignment in assignments:
        _, items = pages[assignment["page"]]
        for item in items:
            if item.get("column", item.get("col")) == assignment["column"]:
                item["char"] = assignment["char"]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path, items in pages.values():
        backup = path.parent / "backups"
        backup.mkdir(exist_ok=True)
        shutil.copy2(path, backup / f"chars-before-review-headword-reflow-{stamp}.json")
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n")
    audit_path = args.work_dir / f"review-headword-reflow-{args.start_page:04d}-{args.end_page:04d}.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(f"已写入；审计：{audit_path}")


if __name__ == "__main__":
    main()
