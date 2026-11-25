#!/usr/bin/env python3
"""生成释文候选流的连续重复清理版，不改原始来源或页面标注。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    source = args.input or args.work_dir / "shuowen-reference-candidates.json"
    output = args.output or args.work_dir / "shuowen-reference-candidates-adjacent-deduped.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    entries = data["entries"]

    kept: list[dict] = []
    removed: list[dict] = []
    previous: str | None = None
    for item in entries:
        char = item["candidate"]["char"]
        if char == previous:
            removed.append({
                "source_entry": item["source_entry"],
                "char": char,
                "reason": "user_confirmed_adjacent_duplicate",
            })
            continue
        kept.append(item)
        previous = char

    output.write_text(json.dumps({
        "source": str(source),
        "rule": "连续相同候选只保留第一个；由用户确认相邻重复不应保留",
        "entries": kept,
        "removed_adjacent_duplicates": removed,
        "summary": {
            "source_entries": len(entries),
            "removed": len(removed),
            "remaining": len(kept),
        },
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "removed": len(removed), "remaining": len(kept)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
