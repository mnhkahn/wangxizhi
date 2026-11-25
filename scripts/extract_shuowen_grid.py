#!/usr/bin/env python3
"""按版面竖线切分《说文广义》扫描页。

这个脚本只产出列的裁剪图和 columns.json，不会修改人工标注 chars.json。
后续的篆书提取应以这里的列为输入，而不是对整页直接找连通块。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def strongest_line(projection: np.ndarray, start: int, end: int) -> int:
    """取给定范围内竖线的最强暗像素投影位置。"""
    start, end = max(0, start), min(len(projection), end)
    return start + int(np.argmax(projection[start:end]))


def page_boundaries(image: np.ndarray) -> list[list[int]]:
    """检测左右两页的固定宽度列边界。

    每页最靠书脊的一列会略宽/略窄；其余列以竖线间距的中位数向右展开，
    并在预计位置附近重新取实际竖线，因此不依赖整页字符的连通情况。
    """
    height, width = image.shape
    body_top, body_bottom = int(height * 0.17), int(height * 0.95)
    projection = (image[body_top:body_bottom] < 150).sum(axis=0)
    middle = width // 2
    # 每一页的外框竖线：从书脊两侧开始定位，避免把书脊当成栏目线。
    page_starts = [
        strongest_line(projection, 0, min(120, width)),
        strongest_line(projection, middle + 80, middle + 500),
    ]
    page_ends = [
        strongest_line(projection, middle - 500, middle - 80),
        strongest_line(projection, width - 120, width),
    ]

    pages: list[list[int]] = []
    for left, right in zip(page_starts, page_ends):
        # 第一格的宽度与其它格不同，先在合理范围内找下一条竖线。
        first = strongest_line(projection, left + 220, left + 560)
        boundaries = [left, first]
        # 其余网格的宽度由可见的第二格开始估计；该书约为 360px（300dpi 源图）。
        pitch = 360
        while boundaries[-1] + pitch * 0.55 < right:
            expected = boundaries[-1] + pitch
            if expected - 115 >= right - 40:
                boundaries.append(right)
                break
            candidate = strongest_line(projection, expected - 115, min(right, expected + 116))
            if candidate >= right - 40:
                boundaries.append(right)
                break
            if candidate <= boundaries[-1] + 120:
                candidate = min(right, expected)
            boundaries.append(candidate)
            if right - candidate < pitch * 0.55:
                break
        if boundaries[-1] != right:
            boundaries.append(right)
        # 去重并维持严格递增。
        pages.append(sorted(set(boundaries)))
    return pages


def main() -> None:
    parser = argparse.ArgumentParser(description="以竖线把《说文广义》扫描页切成固定宽度列")
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    image = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(args.image)
    pages = page_boundaries(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))

    crops_dir = args.output / "columns"
    crops_dir.mkdir(parents=True, exist_ok=True)
    columns: list[dict[str, object]] = []
    for page_index, boundaries in enumerate(pages):
        for column_index, (x1, x2) in enumerate(zip(boundaries, boundaries[1:])):
            filename = f"page-{page_index}-column-{column_index:02d}.jpg"
            cv2.imwrite(str(crops_dir / filename), image[:, x1:x2])
            columns.append({
                "page": page_index,
                "column": column_index,
                "bbox": [x1, 0, x2, image.shape[0]],
                "image": f"columns/{filename}",
            })

    manifest = {"source": str(args.image), "pages": pages, "columns": columns}
    (args.output / "columns.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    print(f"切出 {len(columns)} 列；清单：{args.output / 'columns.json'}")


if __name__ == "__main__":
    main()
