#!/usr/bin/env python3
"""校验《说文广义》下载释文中被拆错的字头。

下载数据的 headword 有时会把同一版面行里的下一个字也记成前一字。
本工具不猜字：同一 headword_line_id 的后续条目必须在纠错表中明确标为
headword 或 continuation，否则输出待核清单并拒绝重排。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start-entry", type=int, default=1)
    args = parser.parse_args()

    source = json.loads((args.work_dir / "shidian-glosses.json").read_text())["entries"]
    resolutions_path = args.work_dir / "shidian-gloss-resolutions.json"
    resolutions = (
        json.loads(resolutions_path.read_text()).get("entries", {})
        if resolutions_path.exists()
        else {}
    )
    first_by_line = {}
    unresolved = []
    for index, entry in enumerate(source, 1):
        if index < args.start_entry:
            continue
        line = str(entry.get("headword_line_id"))
        if line not in first_by_line:
            first_by_line[line] = index
            continue
        resolution = resolutions.get(str(index))
        if resolution is None:
            unresolved.append({
                "entry": index,
                "same_as_entry": first_by_line[line],
                "raw_headword": entry.get("headword"),
                "gloss": entry.get("gloss"),
            })
    report = args.work_dir / f"shidian-unresolved-headwords-{args.start_entry:04d}.json"
    report.write_text(json.dumps(unresolved, ensure_ascii=False, indent=2) + chr(10))
    print(f"待核 {len(unresolved)} 条：{report}")
    if unresolved:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
