#!/usr/bin/env python3
"""依据《说文广义》的网格版式提出篆书框（不写入 chars.json）。

规则：先使用 extract_shuowen_grid.py 给出的竖线列；正文中的篆书列与释文列
交替。篆书列顶部通常留白；若顶部先出现一个明显较小的字，视为释文并跳过。
其余字形以固定高度的槽位截取。结果另存为 seal-proposals.json，供人工核对。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


BODY_TOP = 1100
BODY_BOTTOM = 4800
BOX_HEIGHT = 397
DEFAULT_STEP = 570
MIN_FALLBACK_INK = 1000


def ink_runs(image: np.ndarray, x1: int, x2: int) -> list[tuple[int, int]]:
    """得到一列中连续的大字墨迹段；小空隙会被合并。"""
    # 原扫描的竖线会有断续残影；保留 80px 内边距，避免将边线当成篆书。
    crop = image[BODY_TOP:BODY_BOTTOM, x1 + 80:x2 - 80]
    active = (crop < 105).sum(axis=1) >= 3
    # 篆书笔画中短暂的空行不应把同一个字拆成两段。
    for _ in range(50):
        active[1:-1] |= active[:-2] & active[2:]
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, is_active in enumerate(active):
        if is_active and start is None:
            start = index
        if start is not None and (not is_active or index == len(active) - 1):
            end = index if not is_active else index + 1
            if end - start >= 120:
                runs.append((BODY_TOP + start, BODY_TOP + end))
            start = None
    return runs


def proposal_boxes(image: np.ndarray, manifest: dict[str, object]) -> list[dict[str, object]]:
    """从交替网格列中提出固定高度的篆书框。"""
    result: list[dict[str, object]] = []
    for column in manifest["columns"]:  # type: ignore[index]
        page = int(column["page"])
        index = int(column["column"])
        x1, _, x2, _ = map(int, column["bbox"])
        # 本页的篆书和释文交替。左页第 0 格是页边说明，排除；右页从第 0 格起。
        if index % 2 or (page == 0 and index == 0):
            continue

        runs = ink_runs(image, x1, x2)
        heights = [end - start for start, end in runs if 180 <= end - start <= 520]
        if not heights:
            continue
        typical_height = float(np.median(heights))
        # 顶部单个小字是释文，不作为篆书框的起点。只跳过第一段：后续字形
        # 即使写得较小，仍是同一篆书列的异体，不能误删。
        usable = list(runs)
        first_start, first_end = usable[0]
        if (
            first_start < BODY_TOP + 250
            and first_end - first_start < typical_height * 0.75
        ):
            usable.pop(0)
        if not usable:
            continue

        previous_center: float | None = None
        for start, end in usable:
            height = end - start
            if height > typical_height * 1.55 and previous_center is not None:
                # 被连通的连续字形按固定字距补槽；每槽仍须有实际墨迹才保留。
                centers = np.arange(previous_center + DEFAULT_STEP, end, DEFAULT_STEP)
            else:
                centers = np.array([(start + end) / 2])
            for center in centers:
                box_y1 = int(round(center - BOX_HEIGHT / 2))
                box_y2 = box_y1 + BOX_HEIGHT
                # 使用整列内部的固定宽度，避免把左右竖线纳入字符框。
                center_x = (x1 + x2) / 2
                box_x1 = int(round(center_x - 150))
                box_x2 = int(round(center_x + 150))
                result.append({
                    "page": page,
                    "grid_column": index,
                    "char": "",
                    "bbox": [box_x1, box_y1, box_x2, box_y2],
                })
                previous_center = float(center)
            if height <= typical_height * 1.55:
                previous_center = (start + end) / 2
    return result


def proposal_boxes_by_gaps(image: np.ndarray, manifest: dict[str, object]) -> list[dict[str, object]]:
    """通用版：不假定隔列，直接用列内的大留白识别篆书槽位。

    个别篆字笔画很淡，或首字紧贴正文，会使 ``ink_runs`` 漏掉一格。
    已找到至少两格的列会按其余字的间距推算缺口；候选格仍须含有足够
    墨迹，避免把真正的留白误补成字框。
    """
    result: list[dict[str, object]] = []
    for column in manifest["columns"]:  # type: ignore[index]
        page, index = int(column["page"]), int(column["column"])
        x1, _, x2, _ = map(int, column["bbox"])
        runs = ink_runs(image, x1, x2)
        column_boxes: list[list[int]] = []
        for run_index, (start, end) in enumerate(runs):
            height = end - start
            gap_before = start - runs[run_index - 1][1] if run_index else start - BODY_TOP
            gap_after = runs[run_index + 1][0] - end if run_index + 1 < len(runs) else 0
            # 正文单字约 120–220px 且彼此紧贴；篆书字形更高，并以大留白分隔。
            if height < 240 or max(gap_before, gap_after) < 160:
                continue
            # 顶部无留白的第一个大字是释文标题，不当作篆书。
            if run_index == 0 and gap_before < 160:
                continue
            center_x = (x1 + x2) / 2
            center_y = (start + end) / 2
            box_y1 = int(round(center_y - BOX_HEIGHT / 2))
            box = [
                int(round(center_x - 150)), box_y1,
                int(round(center_x + 150)), box_y1 + BOX_HEIGHT,
            ]
            # 页边装订痕或裁切边可能被网格误分成一列；越出图像的候选
            # 不可能是完整篆字，直接跳过。
            if box[0] >= 0 and box[2] <= image.shape[1]:
                column_boxes.append(box)

        # 以本列已识别的规则字距补检测漏掉的首字/中间字。
        centers = sorted((box[1] + box[3]) / 2 for box in column_boxes)
        if len(centers) >= 2:
            deltas = [right - left for left, right in zip(centers, centers[1:])]
            normal_deltas = [delta for delta in deltas if 400 <= delta <= 750]
            if normal_deltas:
                normal_step = float(np.median(normal_deltas))
                expected: list[float] = []
                # 正常篆字列的首格中心约为 1,500；首个候选明显更靠下时，
                # 反推它前面的漏字。
                # 仅补一个紧邻的首格。若首个已识别字已在 2,300px 以下，
                # 上方通常是该条目的自然留白；继续反推会把破损或装订痕迹
                # 当成字形（如第 35 页）。
                if centers[0] <= 2300:
                    center = centers[0] - normal_step
                    if center >= BODY_TOP + BOX_HEIGHT / 2 - 30:
                        expected.append(center)
                # 中间留白可能是版式空白、纸张破损或装订痕迹，不自动补框；
                # 这类位置仅保留给人工确认后再补。

                box_x1 = int(round((x1 + x2) / 2 - 150))
                box_x2 = int(round((x1 + x2) / 2 + 150))
                for center in expected:
                    # 补推的候选也必须完整落在图内，不能把页边、装订线
                    # 当作一列篆字。
                    if box_x1 < 0 or box_x2 > image.shape[1]:
                        continue
                    box_y1 = int(round(center - BOX_HEIGHT / 2))
                    box = [box_x1, box_y1, box_x2, box_y1 + BOX_HEIGHT]
                    if any(abs(center - old_center) < 80 for old_center in centers):
                        continue
                    ink = image[box[1]:box[3], box[0] + 80:box[2] - 80]
                    if int((ink < 105).sum()) >= MIN_FALLBACK_INK:
                        column_boxes.append(box)

        for box in sorted(column_boxes, key=lambda item: item[1]):
            result.append({
                "page": page,
                "grid_column": index,
                "char": "",
                "bbox": box,
            })
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("grid", type=Path, help="extract_shuowen_grid.py 生成的 columns.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preview", type=Path, help="可选：写出带红框的整页预览图")
    parser.add_argument("--mode", choices=("alternating", "gaps"), default="alternating")
    args = parser.parse_args()

    image = cv2.imread(str(args.image), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(args.image)
    manifest = json.loads(args.grid.read_text())
    proposals = proposal_boxes_by_gaps(image, manifest) if args.mode == "gaps" else proposal_boxes(image, manifest)
    args.output.write_text(json.dumps(proposals, ensure_ascii=False, indent=2) + "\n")
    if args.preview:
        preview = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
        assert preview is not None
        for item in proposals:
            x1, y1, x2, y2 = item["bbox"]
            cv2.rectangle(preview, (x1, y1), (x2, y2), (0, 0, 255), 12)
        cv2.imwrite(str(args.preview), preview)
    print(f"提出 {len(proposals)} 个篆书框：{args.output}")


if __name__ == "__main__":
    main()
