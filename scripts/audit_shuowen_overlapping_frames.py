#!/usr/bin/env python3
"""只读检查《说文广义》页面中相交的字框。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def overlap(a: list[float], b: list[float]) -> tuple[float, float, float]:
    """返回相交宽、高、面积；边缘刚好接触不算重叠。"""
    width = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return width, height, width * height


def main() -> None:
    parser = argparse.ArgumentParser(description="只读审计重叠的《说文广义》字框")
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start-page", type=int, default=0)
    parser.add_argument("--end-page", type=int, default=9999)
    parser.add_argument("--min-ratio", type=float, default=0.02,
                        help="相交面积占较小框面积的最小比例，默认 2%%")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    findings: list[dict] = []
    for chars_path in sorted(args.work_dir.glob(".debug/fatie-*/chars.json")):
        page = int(chars_path.parent.name.split("-")[-1])
        if not args.start_page <= page <= args.end_page:
            continue
        entries = json.loads(chars_path.read_text())
        for left_index, left in enumerate(entries):
            a = [float(value) for value in left["bbox"]]
            area_a = (a[2] - a[0]) * (a[3] - a[1])
            if area_a <= 0:
                continue
            for right_index in range(left_index + 1, len(entries)):
                right = entries[right_index]
                b = [float(value) for value in right["bbox"]]
                area_b = (b[2] - b[0]) * (b[3] - b[1])
                if area_b <= 0:
                    continue
                width, height, area = overlap(a, b)
                ratio = area / min(area_a, area_b)
                if ratio < args.min_ratio:
                    continue
                findings.append({
                    "page": page,
                    "left": {"entry_index": left_index, "column": left.get("column", left.get("col")),
                             "row": left.get("row"), "bbox": left["bbox"]},
                    "right": {"entry_index": right_index, "column": right.get("column", right.get("col")),
                              "row": right.get("row"), "bbox": right["bbox"]},
                    "overlap": {"width": round(width, 2), "height": round(height, 2),
                                "area": round(area, 2), "min_area_ratio": round(ratio, 4)},
                })

    report = {"range": [args.start_page, args.end_page], "min_ratio": args.min_ratio,
              "count": len(findings), "findings": findings}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
