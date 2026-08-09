#!/usr/bin/env python3
"""用已核对的《说文广义》释文流重填既有字框。

不改 bbox、row、column；只按页序和物理横坐标（右至左）更新 char。
同一下载字头行发生拆分错误时，必须由 shidian-gloss-resolutions.json
明确标为新字头或续文，避免“重复字直接删除”的错误。
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


def source_labels(work_dir: Path, start_entry: int) -> list[tuple[int, str]]:
    entries = json.loads((work_dir / "shidian-glosses.json").read_text())["entries"]
    resolutions = json.loads(
        (work_dir / "shidian-gloss-resolutions.json").read_text()
    )["entries"]
    labels = []
    for index, entry in enumerate(entries, 1):
        if index < start_entry:
            continue
        rule = resolutions.get(str(index))
        if rule and rule["kind"] == "continuation":
            continue
        label = rule.get("char") if rule else entry.get("headword")
        if not isinstance(label, str) or len(label) != 1:
            raise ValueError(f"第 {index} 条没有可用单字头")
        labels.append((index, label))
    return labels


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start-page", type=int, required=True)
    parser.add_argument("--end-page", type=int, required=True)
    parser.add_argument("--start-entry", type=int, required=True)
    parser.add_argument(
        "--allow-tail-blanks",
        action="store_true",
        help="释文少于物理列时，明确允许范围末尾字槽留空",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    labels = source_labels(args.work_dir, args.start_entry)
    pages, slots = {}, []
    for page in range(args.start_page, args.end_page + 1):
        path = args.work_dir / ".debug" / f"fatie-{page:04d}" / "chars.json"
        if not path.exists():
            continue
        items = json.loads(path.read_text())
        groups = {}
        for item in items:
            col = item.get("column", item.get("col"))
            if isinstance(col, int):
                groups.setdefault(col, []).append(item)
        def centre(group):
            return sum((x["bbox"][0] + x["bbox"][2]) / 2 for x in group) / len(group)
        for col, _ in sorted(groups.items(), key=lambda pair: centre(pair[1]), reverse=True):
            slots.append((page, col))
        pages[page] = [path, items]
    if len(labels) < len(slots) and not args.allow_tail_blanks:
        raise ValueError(f"纠正后释文仅 {len(labels)} 字，框有 {len(slots)} 列")
    assigned = labels[:len(slots)]
    if len(assigned) < len(slots):
        assigned += [(None, "")] * (len(slots) - len(assigned))
    audit = {
        "start_entry": args.start_entry,
        "slots": len(slots),
        "source_used": [labels[0][0], assigned[min(len(labels), len(slots)) - 1][0]],
        "unused_labels": [
            {"entry": index, "char": label}
            for index, label in labels[len(slots):]
        ],
        "tail_blanks": max(0, len(slots) - len(labels)),
    }
    print(json.dumps(audit, ensure_ascii=False))
    if not args.apply:
        return
    for (page, col), (_, label) in zip(slots, assigned):
        _, items = pages[page]
        for item in items:
            if item.get("column", item.get("col")) == col:
                item["char"] = label
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path, items in pages.values():
        backup = path.parent / "backups"
        backup.mkdir(exist_ok=True)
        shutil.copy2(path, backup / f"chars-before-resolved-gloss-reflow-{stamp}.json")
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + chr(10))
    audit_path = args.work_dir / f"resolved-gloss-reflow-{args.start_page:04d}-{args.end_page:04d}.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + chr(10))
    print(f"已写入；审计：{audit_path}")


if __name__ == "__main__":
    main()
