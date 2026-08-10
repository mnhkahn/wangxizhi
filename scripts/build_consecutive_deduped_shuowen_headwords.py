#!/usr/bin/env python3
"""保守提取《说文广义》释文字头，绝不静默丢弃疑似独立字。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def looks_like_independent_entry(previous: dict, current: dict) -> bool:
    """判断同字头的后一条是否显然是一条新的释文，而非续行。"""
    before = str(previous.get("gloss", "")).strip()
    after = str(current.get("gloss", "")).strip()
    if "百" in after and "部" in after:
        return True
    return len(before) >= 12 and len(after) >= 12 and "从" in before and "从" in after


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    entries = json.loads((args.work_dir / "shidian-glosses.json").read_text())["entries"]
    exceptions_path = args.work_dir / "shidian-consecutive-dedup-exceptions.json"
    exceptions = json.loads(exceptions_path.read_text()) if exceptions_path.exists() else {}
    preserved_entries = {int(index) for index in exceptions.get("preserve_source_entries", [])}
    continuation_entries = {int(index) for index in exceptions.get("continuation_source_entries", [])}
    overrides = {int(index): str(char) for index, char in exceptions.get("headword_overrides", {}).items()}
    resolutions_path = args.work_dir / "shidian-gloss-resolutions.json"
    resolutions = json.loads(resolutions_path.read_text()).get("entries", {}) if resolutions_path.exists() else {}
    for key, rule in resolutions.items():
        index = int(key)
        if rule.get("kind") == "continuation":
            continuation_entries.add(index)
        elif rule.get("kind") == "headword":
            overrides[index] = str(rule["char"])
    kept, removed, unresolved = [], [], []
    previous = None
    for index, entry in enumerate(entries, 1):
        raw_char = str(entry.get("headword", "")).strip()
        char = overrides.get(index, raw_char)
        if raw_char == previous and index not in preserved_entries and index not in overrides:
            if index not in continuation_entries and looks_like_independent_entry(entries[index - 2], entry):
                # 保留槽位，避免错误去重让后面的每个字错位；但字头本身仍需校勘。
                kept.append({
                    "source_entry": index,
                    "char": char,
                    "status": "unresolved_duplicate_headword",
                    "raw_headword": raw_char,
                })
                unresolved.append({
                    "source_entry": index,
                    "raw_headword": raw_char,
                    "gloss": str(entry.get("gloss", "")).strip(),
                })
                previous = raw_char
                continue
            removed.append({"source_entry": index, "char": char})
            continue
        kept.append({"source_entry": index, "char": char})
        previous = raw_char

    result = {
        "source": "shidian-glosses.json",
        "rule": "仅删除明确续行；疑似独立的连续同字头保留为待校勘条目",
        "exceptions": str(exceptions_path.name) if exceptions_path.exists() else None,
        "resolutions": str(resolutions_path.name) if resolutions_path.exists() else None,
        "preserved_consecutive_entries": sorted(preserved_entries),
        "continuation_source_entries": sorted(continuation_entries),
        "headword_overrides": {str(index): char for index, char in sorted(overrides.items())},
        "original_records": len(entries),
        "removed_consecutive_duplicates": len(removed),
        "unresolved_duplicate_headwords": unresolved,
        "headwords": kept,
        "removed": removed,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        f"原始 {len(entries)} 条；删除明确续行 {len(removed)} 条；"
        f"待校勘同字头 {len(unresolved)} 条；保留 {len(kept)} 条"
    )


if __name__ == "__main__":
    main()
