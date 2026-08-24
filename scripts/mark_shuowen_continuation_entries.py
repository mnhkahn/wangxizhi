#!/usr/bin/env python3
"""把《史典》OCR误拆出的释文续行显式标为不占篆字槽。"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path


# 这些行不是独立字头：句首引文、声训/反切行，或只有反切的断行。
CONTINUATION = re.compile(r"^(?:曰[：:]|聲[。．，、]|[\u3400-\u9fff]{1,5}切[。．]?)$")


def is_continuation(gloss: str) -> bool:
    """只命中不能自成释文的高置信续行；不猜测真正字头。"""
    return bool(CONTINUATION.match(gloss.strip()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start-entry", type=int, default=1)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    source_path = args.work_dir / "shidian-glosses.json"
    rules_path = args.work_dir / "shidian-gloss-resolutions.json"
    entries = json.loads(source_path.read_text())["entries"]
    document = json.loads(rules_path.read_text()) if rules_path.exists() else {"entries": {}}
    rules: dict[str, dict] = document.setdefault("entries", {})

    candidate_numbers: set[int] = set()
    for number, entry in enumerate(entries, 1):
        if number >= args.start_entry and (
            str(entry.get("headword", "")).strip() == "聲"
            or is_continuation(str(entry.get("gloss", "")))
        ):
            candidate_numbers.add(number)

    candidates = []
    for number in sorted(candidate_numbers):
        if str(number) in rules:
            continue
        entry = entries[number - 1]
        candidates.append({
            "entry": number,
            "raw_headword": entry.get("headword", ""),
            "gloss": str(entry.get("gloss", "")).strip(),
        })

    print(json.dumps({"count": len(candidates), "candidates": candidates}, ensure_ascii=False, indent=2))
    if not args.apply:
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = rules_path.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    if rules_path.exists():
        shutil.copy2(rules_path, backup_dir / f"shidian-gloss-resolutions-before-continuation-mark-{stamp}.json")
    for item in candidates:
        rules[str(item["entry"])] = {
            "kind": "continuation",
            "note": f"OCR 将释文续行“{item['gloss']}”误拆为独立字头；不占篆字槽。",
        }
    rules_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    print(f"已写入 {len(candidates)} 条 continuation：{rules_path}")


if __name__ == "__main__":
    main()
