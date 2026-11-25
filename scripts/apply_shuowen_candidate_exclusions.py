#!/usr/bin/env python3
"""把已确认无对应字框的候选项排除，生成可重排的候选流。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    args = parser.parse_args()
    source = args.work_dir / "shuowen-reference-candidates-adjacent-deduped.json"
    exclusions_path = args.work_dir / "shuowen-reference-candidate-exclusions.json"
    output = args.work_dir / "shuowen-reference-candidates-resolved.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    rules = json.loads(exclusions_path.read_text(encoding="utf-8")).get("entries", {})
    kept, removed, overrides = [], [], []
    for item in data["entries"]:
        source_entry = str(item["source_entry"])
        rule = rules.get(source_entry)
        if rule and rule.get("kind") == "continuation":
            removed.append({"source_entry": item["source_entry"], "char": item["candidate"]["char"], **rule})
            continue
        if rule and rule.get("kind") == "headword":
            char = rule.get("char")
            if not isinstance(char, str) or len(char) != 1:
                raise ValueError(f"第 {source_entry} 条 headword 覆写不是单字")
            item = {**item, "candidate": {**item["candidate"], "char": char}}
            overrides.append({"source_entry": item["source_entry"], "char": char, **rule})
        kept.append(item)
    output.write_text(json.dumps({
        "source": str(source),
        "exclusions": str(exclusions_path),
        "entries": kept,
        "removed": removed,
        "overrides": overrides,
        "summary": {"before": len(data["entries"]), "removed": len(removed), "overrides": len(overrides), "remaining": len(kept)},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "removed": removed, "overrides": overrides, "remaining": len(kept)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
