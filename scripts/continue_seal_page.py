#!/usr/bin/env python3
"""依据已人工框选的篆书样例，为同页生成待确认的篆书候选框。

不读取或覆盖 chars.json；候选写到同目录的 seal_candidates.json。
释文标签由人工样例保留，候选的 char 为空，待确认后再写入 chars.json。
"""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

import cv2
import numpy as np


def vertical_bands(gray: np.ndarray, seed_width: float) -> list[tuple[int, int]]:
    """按竖直框线分栏，保留与样例字框宽度相近的栏。"""
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY_INV, 71, 15)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(60, gray.shape[0] // 8)))
    lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel)
    strength = (lines > 0).sum(axis=0)
    xs = np.where(strength > gray.shape[0] * 0.2)[0]
    groups: list[tuple[int, int]] = []
    for x in xs:
        if not groups or x > groups[-1][1] + 3:
            groups.append((int(x), int(x)))
        else:
            groups[-1] = (groups[-1][0], int(x))
    centers = [(a + b) // 2 for a, b in groups]
    bands = []
    for left, right in zip(centers, centers[1:]):
        width = right - left
        if seed_width * 0.7 <= width <= seed_width * 2.8:
            bands.append((left + 6, right - 6))
    return bands


def split_band(gray: np.ndarray, x1: int, x2: int) -> list[list[int]]:
    roi = gray[:, x1:x2]
    ink = cv2.adaptiveThreshold(roi, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY_INV, 51, 13)
    margin = max(5, roi.shape[1] // 10)
    ink[:, :margin] = ink[:, -margin:] = 0
    active = (ink > 0).sum(axis=1) > roi.shape[1] * 0.035
    runs, start = [], None
    for y, value in enumerate(active):
        if value and start is None: start = y
        if not value and start is not None:
            if y - start > 80: runs.append([start, y])
            start = None
    if start is not None and len(active) - start > 80: runs.append([start, len(active)])
    return [[x1, top, x2, bottom] for top, bottom in runs]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--seed", type=Path, required=True, help="人工标好的 chars.json")
    parser.add_argument("--apply", action="store_true", help="把候选框追加到 chars.json，供桌面端查看")
    args = parser.parse_args()
    seed = json.loads(args.seed.read_text(encoding="utf-8"))
    gray = cv2.imread(str(args.image), cv2.IMREAD_GRAYSCALE)
    if gray is None or not seed: raise SystemExit("缺少有效图片或样例")
    widths = [item["bbox"][2] - item["bbox"][0] for item in seed]
    seed_width = float(np.median(widths))
    seed_boxes = [item["bbox"] for item in seed]
    candidates = []
    for x1, x2 in vertical_bands(gray, seed_width):
        for box in split_band(gray, x1, x2):
            # 与人工框重叠的候选不重复输出。
            if any(abs((box[0] + box[2]) / 2 - (b[0] + b[2]) / 2) < seed_width * .7
                   and min(box[3], b[3]) > max(box[1], b[1]) for b in seed_boxes):
                continue
            candidates.append({"char": "", "bbox": box, "split_method": "seeded_seal_candidate"})
    output = args.seed.with_name("seal_candidates.json")
    output.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.apply:
        existing = {(tuple(item["bbox"]) if "bbox" in item else ()) for item in seed}
        for index, item in enumerate(candidates):
            if tuple(item["bbox"]) in existing:
                continue
            item.update({"id": str(uuid.uuid4()), "uuid": "", "column": index + 2,
                         "row": 0, "visible": True})
            seed.append(item)
        args.seed.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{output}: {len(candidates)} 个候选（未覆盖人工样例）")

if __name__ == "__main__": main()
