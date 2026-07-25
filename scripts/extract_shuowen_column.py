#!/usr/bin/env python3
"""从《说文广义》的一列篆书中提取字框，并绑定一个释文字符。

示例：
python scripts/extract_shuowen_column.py page.jpg --char 移 --column 38,12,211,554

一列中出现的所有篆书字图都会被标为 ``移``。结果写入与桌面编辑器
兼容的 ``.debug/<图片名>/chars.json``，同时在 ``words/`` 下导出单字裁图。
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

import cv2
import numpy as np


def parse_box(value: str) -> tuple[int, int, int, int]:
    """解析 x1,y1,x2,y2，并验证它是有效矩形。"""
    parts = [int(part.strip()) for part in value.split(",")]
    if len(parts) != 4 or parts[0] >= parts[2] or parts[1] >= parts[3]:
        raise argparse.ArgumentTypeError("列范围应为 x1,y1,x2,y2")
    return tuple(parts)  # type: ignore[return-value]


def find_glyph_rows(gray: np.ndarray, box: tuple[int, int, int, int]) -> list[tuple[int, int]]:
    """用横向墨迹投影找出列中各个篆书字的上下边界。"""
    x1, y1, x2, y2 = box
    roi = gray[y1:y2, x1:x2]
    # 纸张背景不均，用自适应阈值仅保留墨迹；去掉两侧框线。
    ink = cv2.adaptiveThreshold(roi, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY_INV, 51, 13)
    margin = max(4, roi.shape[1] // 12)
    ink[:, :margin] = 0
    ink[:, -margin:] = 0
    projection = (ink > 0).sum(axis=1)
    active = projection > max(2, roi.shape[1] * 0.025)

    runs: list[tuple[int, int]] = []
    start: int | None = None
    for y, value in enumerate(active):
        if value and start is None:
            start = y
        elif not value and start is not None:
            if y - start >= 12:
                runs.append((start, y))
            start = None
    if start is not None and len(active) - start >= 12:
        runs.append((start, len(active)))

    # 同一个字被很小的空隙切开时合并；阈值跟字高成比例。
    merged: list[tuple[int, int]] = []
    for start, end in runs:
        if merged and start - merged[-1][1] < max(8, roi.shape[0] // 40):
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    # 灰尘、页码或残缺的框线会产生很短的假片段。以中位字高过滤它们，
    # 保留高度至少为主字形 55% 的片段。
    if merged:
        median_height = float(np.median([end - start for start, end in merged]))
        merged = [(start, end) for start, end in merged if end - start >= median_height * 0.55]
    return [(y1 + start, y1 + end) for start, end in merged]


def main() -> None:
    parser = argparse.ArgumentParser(description="提取一列《说文广义》篆书字图")
    parser.add_argument("image", type=Path)
    parser.add_argument("--char", required=True, help="对应释文，例如：移")
    parser.add_argument("--column", required=True, type=parse_box, help="篆书列 x1,y1,x2,y2")
    parser.add_argument("--padding", type=int, default=16, help="每个字框额外留白像素")
    args = parser.parse_args()

    image = cv2.imread(str(args.image))
    if image is None:
        raise SystemExit(f"无法读取图片：{args.image}")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    x1, _, x2, _ = args.column
    rows = find_glyph_rows(gray, args.column)

    work_dir = args.image.parent
    stem = args.image.stem
    debug_dir = work_dir / ".debug" / stem
    words_dir = work_dir / "words" / stem
    debug_dir.mkdir(parents=True, exist_ok=True)
    words_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for index, (top, bottom) in enumerate(rows):
        pad = args.padding
        bbox = [max(0, x1 - pad), max(0, top - pad), min(width, x2 + pad), min(height, bottom + pad)]
        crop = image[bbox[1]:bbox[3], bbox[0]:bbox[2]]
        cv2.imwrite(str(words_dir / f"{index:03d}-{args.char}.png"), crop)
        records.append({"id": str(uuid.uuid4()), "char": args.char, "bbox": bbox,
                        "column": 0, "row": index, "global_index": index,
                        "split_method": "shuowen_projection", "visible": True})
    with (debug_dir / "chars.json").open("w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)
    print(f"提取 {len(records)} 个“{args.char}”：{debug_dir / 'chars.json'}")


if __name__ == "__main__":
    main()
