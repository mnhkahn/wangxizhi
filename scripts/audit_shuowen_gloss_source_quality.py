#!/usr/bin/env python3
"""审计识典《说文广义》释文源的可顺排性；绝不修改框或标签。"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


PREFIX = re.compile(r"^([^，。；：、]{1})[，。；：、]")


def is_repeated(value: str) -> bool:
    return len(value) > 1 and len(set(value)) == 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    entries = json.loads((args.work_dir / "shidian-glosses.json").read_text())["entries"]
    by_line = Counter(str(entry.get("headword_line_id")) for entry in entries)
    issues: list[dict[str, object]] = []
    quality = Counter()
    for index, entry in enumerate(entries, 1):
        raw = str(entry.get("headword", "")).strip()
        gloss = str(entry.get("gloss", "")).strip()
        prefix = PREFIX.match(gloss)
        if len(raw) == 1 and by_line[str(entry.get("headword_line_id"))] == 1:
            quality["direct_single"] += 1
            continue
        if len(raw) == 1 and by_line[str(entry.get("headword_line_id"))] > 1:
            quality["shared_title_line"] += 1
            issues.append({
                "source_entry": index,
                "kind": "shared_title_line",
                "raw_headword": raw,
                "gloss_prefix_candidate": prefix.group(1) if prefix else None,
                "gloss": gloss,
            })
            continue
        if is_repeated(raw):
            quality["repeated_ocr_title"] += 1
            issues.append({
                "source_entry": index,
                "kind": "repeated_ocr_title",
                "raw_headword": raw,
                "normalized_candidate": raw[0],
                "gloss_prefix_candidate": prefix.group(1) if prefix else None,
                "gloss": gloss,
            })
            continue
        quality["unresolved_title"] += 1
        issues.append({
            "source_entry": index,
            "kind": "unresolved_title",
            "raw_headword": raw,
            "gloss_prefix_candidate": prefix.group(1) if prefix else None,
            "gloss": gloss,
        })

    result = {
        "source": "shidian-glosses.json",
        "rule": "只审计可直接用于顺排的字头；共享标题行与 OCR 重复标题一律待标准《说文》正文核验。",
        "entries": len(entries),
        "quality_counts": dict(quality),
        "issues": issues,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"entries": len(entries), "quality_counts": dict(quality), "issues": len(issues)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
