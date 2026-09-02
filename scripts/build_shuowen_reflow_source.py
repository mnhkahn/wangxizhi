#!/usr/bin/env python3
"""从已提取的释文字流生成可用于整段顺排的单字源文件。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start-entry", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = json.loads(
        (args.work_dir / "shidian-headwords-consecutive-deduped.json").read_text()
    )["headwords"]
    headwords = []
    for item in source:
        if item["source_entry"] < args.start_entry:
            continue
        raw = str(item.get("char", ""))
        if not raw:
            continue
        # 既有来源的多字项是 OCR 误并的行；保留首个可写字位，审计中标出。
        headwords.append({
            "source_entry": item["source_entry"],
            "char": raw[0],
            "raw": raw,
            "coerced": len(raw) != 1,
        })
    args.output.write_text(
        json.dumps({"headwords": headwords}, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps({"headwords": len(headwords), "coerced": sum(x["coerced"] for x in headwords)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
