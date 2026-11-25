#!/usr/bin/env python3
"""只读校验《说文广义》释文顺排流，确保部首字头不会被静默漏掉。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def frame_slots(work_dir: Path, start_page: int, end_page: int) -> int:
    """按真实横坐标统计物理篆书列数，不依赖历史 column 序号。"""
    total = 0
    for page in range(start_page, end_page + 1):
        path = work_dir / ".debug" / f"fatie-{page:04d}" / "chars.json"
        if not path.exists():
            continue
        groups: dict[int, list[dict]] = {}
        for item in json.loads(path.read_text()):
            column = item.get("column", item.get("col"))
            if isinstance(column, int):
                groups.setdefault(column, []).append(item)
        total += len(groups)
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start-entry", type=int, required=True)
    parser.add_argument(
        "--max-labels", type=int,
        help="只校验为当前重排范围所需的前 N 个有效字头，不预读后文",
    )
    parser.add_argument("--start-page", type=int)
    parser.add_argument("--end-page", type=int)
    args = parser.parse_args()
    if (args.start_page is None) != (args.end_page is None):
        parser.error("--start-page 与 --end-page 必须同时提供")
    slots = (
        frame_slots(args.work_dir, args.start_page, args.end_page)
        if args.start_page is not None else None
    )
    required_labels = args.max_labels if args.max_labels is not None else slots

    entries = json.loads((args.work_dir / "shidian-glosses.json").read_text())["entries"]
    resolutions_path = args.work_dir / "shidian-gloss-resolutions.json"
    resolutions = (
        json.loads(resolutions_path.read_text()).get("entries", {})
        if resolutions_path.exists() else {}
    )
    labels: list[dict] = []
    continuations: list[int] = []
    components: list[dict] = []
    for index, entry in enumerate(entries, 1):
        if index < args.start_entry:
            continue
        rule = resolutions.get(str(index), {})
        if rule.get("kind") == "continuation":
            continuations.append(index)
            continue
        char = rule.get("char", entry.get("headword"))
        if not isinstance(char, str) or len(char) != 1:
            raise ValueError(
                f"第 {index} 条没有可顺排的单字；必须在 "
                "shidian-gloss-resolutions.json 写 headword 或 continuation"
            )
        record = {"entry": index, "char": char}
        labels.append(record)
        if "从" in str(entry.get("gloss", "")) or "從" in str(entry.get("gloss", "")):
            components.append(record)
        if required_labels is not None and len(labels) >= required_labels:
            break
    report = {
        "start_entry": args.start_entry,
        "labels_available": len(labels),
        "only_skipped_entries": {"kind": "continuation", "entries": continuations},
        "component_headwords_included": {
            "count": len(components), "samples": components[:20],
        },
        "frame_slots": slots,
        "labels_minus_slots": None if slots is None else len(labels) - slots,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
