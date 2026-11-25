#!/usr/bin/env python3
"""只提取一列篆书，并把释文标题写入每个字框的 char 字段。"""

import argparse
import json
import uuid
from pathlib import Path

import cv2
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--char", required=True, help="释文标题，如：颸")
    parser.add_argument("--column", required=True, help="篆书列 x1,y1,x2,y2")
    args = parser.parse_args()

    x1, y1, x2, y2 = map(int, args.column.split(","))
    image = cv2.imread(str(args.image), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise SystemExit(f"无法读取：{args.image}")

    roi = image[y1:y2, x1:x2]
    ink = cv2.adaptiveThreshold(roi, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY_INV, 51, 13)
    ink[:, :max(4, ink.shape[1] // 12)] = 0  # 忽略左右框线
    ink[:, -max(4, ink.shape[1] // 12):] = 0
    active = (ink > 0).sum(axis=1) > max(2, ink.shape[1] * 0.025)

    runs, start = [], None
    for y, has_ink in enumerate(active):
        if has_ink and start is None:
            start = y
        elif not has_ink and start is not None:
            if y - start >= 12:
                runs.append([start, y])
            start = None
    if start is not None:
        runs.append([start, len(active)])

    # 合并小间隙，并滤掉灰尘造成的短片段。
    merged = []
    for top, bottom in runs:
        if merged and top - merged[-1][1] < max(8, roi.shape[0] // 40):
            merged[-1][1] = bottom
        else:
            merged.append([top, bottom])
    if merged:
        median = np.median([bottom - top for top, bottom in merged])
        merged = [run for run in merged if run[1] - run[0] >= median * 0.55]

    pad = 16
    records = [{
        "id": str(uuid.uuid4()), "char": args.char,
        "bbox": [max(0, x1 - pad), max(0, y1 + top - pad),
                 min(image.shape[1], x2 + pad), min(image.shape[0], y1 + bottom + pad)],
        "column": 0, "row": index, "global_index": index,
        "split_method": "seal_projection", "visible": True,
    } for index, (top, bottom) in enumerate(merged)]

    output = args.image.parent / ".debug" / args.image.stem / "chars.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{output}: {len(records)} 个“{args.char}”篆书框")


if __name__ == "__main__":
    main()
