#!/usr/bin/env python3
"""依据已有篆字框，找同列中漏掉的标准字框（仅输出候选和预览）。"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

import cv2
import numpy as np


def group_columns(entries: list[dict], tolerance: float = 180) -> list[list[dict]]:
    """按中心 x 聚合，结果按右至左排列。"""
    groups: list[list[dict]] = []
    for item in sorted(entries, key=lambda row: (row["bbox"][0] + row["bbox"][2]) / 2):
        center = (item["bbox"][0] + item["bbox"][2]) / 2
        if groups:
            previous = np.mean([(row["bbox"][0] + row["bbox"][2]) / 2 for row in groups[-1]])
            if abs(center - previous) <= tolerance:
                groups[-1].append(item)
                continue
        groups.append([item])
    return list(reversed(groups))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("chars_json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="将候选框追加到 chars.json")
    parser.add_argument("--no-missing-columns", action="store_true", help="不推断整列缺失，仅补已有列")
    parser.add_argument("--threshold", type=int, default=100, help="深色墨迹阈值")
    parser.add_argument("--minimum-ink", type=float, default=0.55, help="相对已有框中位墨量的最低比例")
    args = parser.parse_args()

    entries = json.loads(args.chars_json.read_text())
    image = cv2.imread(str(args.image))
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    groups = group_columns(entries)
    all_heights = [row["bbox"][3] - row["bbox"][1] for row in entries]
    height = int(round(np.median(all_heights)))
    # 相邻行的稳定间距，适合本书页面的等高栅格。
    row_clusters: list[list[float]] = []
    for top_value in sorted(row["bbox"][1] for row in entries):
        if not row_clusters or abs(top_value - np.median(row_clusters[-1])) > 160:
            row_clusters.append([top_value])
        else:
            row_clusters[-1].append(top_value)
    row_tops = [float(np.median(cluster)) for cluster in row_clusters]
    gaps = [b - a for a, b in zip(row_tops, row_tops[1:]) if 450 < b - a < 700]
    pitch = int(round(np.median(gaps)))
    top = int(round(row_tops[0]))
    candidates: list[dict] = []
    page_ink: list[int] = []
    for item in entries:
        bx1, by1, bx2, by2 = map(int, item["bbox"])
        page_ink.append(int((gray[by1:by2, bx1:bx2] < args.threshold).sum()))

    for column, group in enumerate(groups):
        x1 = int(round(np.median([row["bbox"][0] for row in group])))
        width = int(round(np.median([row["bbox"][2] - row["bbox"][0] for row in group])))
        existing_ink = []
        for row in group:
            bx1, by1, bx2, by2 = map(int, row["bbox"])
            existing_ink.append(int((gray[by1:by2, bx1:bx2] < args.threshold).sum()))
        minimum = float(np.median(existing_ink)) * args.minimum_ink
        # 列的起始框可作为种子；继续检查下方标准栅格。只有墨量达到
        # 本列已有字框的比例门槛时才提出候选，因此空白区不会被补成框。
        # 当前页的最深已有框确定版心末行；不扫到底部页码/边框区域。
        maximum_row = len(row_tops) - 1
        for row in range(0, maximum_row + 1):
            y1 = top + row * pitch
            y2 = y1 + height
            # 以实际框的中心位置去重，避免重跑时因行距微调而重复追加。
            if any(abs(((item["bbox"][1] + item["bbox"][3]) / 2) - ((y1 + y2) / 2)) < height * 0.55 for item in group):
                continue
            ink = int((gray[y1:y2, x1:x1 + width] < args.threshold).sum())
            if ink >= minimum:
                candidates.append({
                    "column": column,
                    "row": row,
                    "bbox": [x1, y1, x1 + width, y2],
                    "ink": ink,
                })

    # 若两列中心距接近两倍标准列距，则中间可能整列漏检。对空栏的
    # 每个标准行做同样的墨迹校验；不依赖该列已有种子框。
    if not args.no_missing_columns:
        centers = [float(np.median([(item["bbox"][0] + item["bbox"][2]) / 2 for item in group])) for group in groups]
        gaps = [centers[index] - centers[index + 1] for index in range(len(centers) - 1)]
        normal_gaps = [gap for gap in gaps if gap > 400]
        normal_gap = float(np.median(normal_gaps))
        width = int(round(np.median([row["bbox"][2] - row["bbox"][0] for row in entries])))
        page_minimum = float(np.median(page_ink)) * args.minimum_ink
        for right_column, gap in enumerate(gaps):
            missing_count = round(gap / normal_gap) - 1
            if missing_count < 1 or gap < normal_gap * 1.75:
                continue
            for step in range(1, missing_count + 1):
                center = centers[right_column] - normal_gap * step
                x1 = int(round(center - width / 2))
                for row in range(0, maximum_row + 1):
                    y1 = top + row * pitch
                    y2 = y1 + height
                    ink = int((gray[y1:y2, x1:x1 + width] < args.threshold).sum())
                    if ink >= page_minimum:
                        candidates.append({
                            "column": right_column + step,
                            "row": row,
                            "bbox": [x1, y1, x1 + width, y2],
                            "ink": ink,
                        })

    for row in entries:
        x1, y1, x2, y2 = map(int, row["bbox"])
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 220, 0), 20)
    for row in candidates:
        x1, y1, x2, y2 = row["bbox"]
        cv2.rectangle(image, (x1, y1), (x2, y2), (255, 0, 0), 20)
        cv2.putText(image, "candidate", (x1, y1 - 25), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 0, 0), 8)

    if args.apply:
        for candidate in candidates:
            seed = groups[candidate["column"]][0]
            identifier = uuid.uuid4().hex
            new_entry = {
                **{key: value for key, value in seed.items() if key not in {"id", "uuid", "char", "bbox", "column", "row"}},
                "id": identifier,
                "uuid": identifier,
                "char": "",
                "bbox": candidate["bbox"],
                "column": candidate["column"],
                "row": candidate["row"],
            }
            entries.append(new_entry)
        args.chars_json.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output), image)
    print(json.dumps(candidates, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
