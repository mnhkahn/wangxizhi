#!/usr/bin/env python3
"""按原图像素审计《说文广义》可能为空的标注框；默认不改任何数据。"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np


def ink_ratio(gray: np.ndarray, bbox: list[int]) -> tuple[float, int, int]:
    """返回去除边缘后的墨迹比例、阈值与有效像素数。"""
    x1, y1, x2, y2 = map(int, bbox)
    inset_x = max(8, int((x2 - x1) * 0.13))
    inset_y = max(8, int((y2 - y1) * 0.10))
    crop = gray[y1 + inset_y:y2 - inset_y, x1 + inset_x:x2 - inset_x]
    if crop.size == 0:
        return 0.0, 0, 0
    paper = float(np.percentile(crop, 82))
    threshold = int(max(95, min(180, paper - 38)))
    return float((crop < threshold).mean()), threshold, int(crop.size)


def main() -> None:
    parser = argparse.ArgumentParser(description="按像素找《说文广义》空框候选（只读）")
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--end-page", type=int, default=9999)
    parser.add_argument("--max-ink-ratio", type=float, default=0.012,
                        help="低于此比例视为候选；默认 1.2%%")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    candidates: list[dict] = []
    scanned = 0
    by_page: dict[int, list[float]] = defaultdict(list)
    for page in range(args.start_page, args.end_page + 1):
        chars_path = args.work_dir / ".debug" / f"fatie-{page:04d}" / "chars.json"
        image_path = args.work_dir / f"fatie-{page:04d}.webp"
        if not chars_path.exists() or not image_path.exists():
            continue
        gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        for index, item in enumerate(json.loads(chars_path.read_text())):
            bbox = item.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            ratio, threshold, pixels = ink_ratio(gray, bbox)
            scanned += 1
            by_page[page].append(ratio)
            if ratio <= args.max_ink_ratio:
                candidates.append({
                    "page": page,
                    "column": item.get("column", item.get("col")),
                    "row": item.get("row"),
                    "char": item.get("char", ""),
                    "bbox": bbox,
                    "ink_ratio": round(ratio, 5),
                    "threshold": threshold,
                    "pixels": pixels,
                    "entry_index": index,
                })
    candidates.sort(key=lambda item: (item["ink_ratio"], item["page"], item["column"] or -1, item["row"] or -1))
    result = {
        "mode": "read_only_pixel_audit",
        "range": [args.start_page, args.end_page],
        "frames_scanned": scanned,
        "max_ink_ratio": args.max_ink_ratio,
        "candidate_count": len(candidates),
        "page_median_ink_ratio": {
            str(page): round(float(np.median(values)), 5) for page, values in sorted(by_page.items())
        },
        "candidates": candidates,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"扫描 {scanned} 个框；空框候选 {len(candidates)} 个；输出：{args.output}")
    for item in candidates[:80]:
        print(f"{item['page']:04d} col={item['column']} row={item['row']} 字={item['char']} 墨迹={item['ink_ratio']:.3%}")


if __name__ == "__main__":
    main()
