#!/usr/bin/env python3
"""全页扫描篆书大字候选，并与人工框进行只读比对。

不会修改 chars.json。用于校准《说文广义》这类固定版式的检测参数。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

import cv2


def iou(first: Sequence[float], second: Sequence[float]) -> float:
    """计算两个 [x1, y1, x2, y2] 框的交并比。"""
    x1, y1 = max(first[0], second[0]), max(first[1], second[1])
    x2, y2 = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    if not intersection:
        return 0.0
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / (first_area + second_area - intersection)


def detect_candidates(image_path: Path) -> list[list[float]]:
    """不借助人工框，扫描整页中大小接近篆书大字的连通区域。"""
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(image_path)

    ink = (image < 105).astype("uint8") * 255
    # 页眉、页脚不属于正文篆书区；膨胀使一字的分离笔画合为一个候选区域。
    ink[:1150] = 0
    ink[4800:] = 0
    kernel_size = 31
    merged = cv2.dilate(
        ink, cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    )
    _, _, stats, _ = cv2.connectedComponentsWithStats(merged)

    candidates: list[list[float]] = []
    margin = kernel_size // 2
    for x, y, width, height, area in stats[1:]:
        fill_ratio = area / (width * height)
        if not (150 <= width <= 460 and 180 <= height <= 520 and fill_ratio > 0.12):
            continue
        candidates.append([x + margin, y + margin, x + width - margin, y + height - margin])
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("chars_json", type=Path)
    parser.add_argument("--threshold", type=float, default=0.4, help="命中 IoU，默认 0.4")
    args = parser.parse_args()

    annotations = json.loads(args.chars_json.read_text())
    candidates = detect_candidates(args.image)
    scores = [max((iou(item["bbox"], box) for box in candidates), default=0.0) for item in annotations]
    matched = sum(score >= args.threshold for score in scores)
    print(f"自动候选：{len(candidates)}")
    print(f"人工框：{len(annotations)}；IoU ≥ {args.threshold:g} 命中：{matched}")
    for item, score in zip(annotations, scores):
        if score < args.threshold:
            print(f"未命中  column={item['column']}: {item['bbox']}  best_iou={score:.3f}")


if __name__ == "__main__":
    main()
