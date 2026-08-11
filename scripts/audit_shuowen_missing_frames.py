#!/usr/bin/env python3
"""只读审计《说文广义》的多框、少列和少框问题。

不使用 OCR、不写 chars.json。判定依据是固定版格、篆书大字墨迹段和同页共同
行基线；页面仅因边缘少一个网格而空着时，不会被报告为缺列。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from frame_shuowen_volume import active_runs, grid_lines


def grouped(items: list[dict]) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = defaultdict(list)
    for item in items:
        column = item.get("column", item.get("col"))
        if isinstance(column, int):
            result[column].append(item)
    return result


def nearest_grid(group: list[dict], centers: list[float]) -> int | None:
    center = sum((item["bbox"][0] + item["bbox"][2]) / 2 for item in group) / len(group)
    index = min(range(len(centers)), key=lambda value: abs(centers[value] - center))
    return index if abs(centers[index] - center) <= 78 else None


def seal_runs(gray: np.ndarray, left: int, right: int) -> list[tuple[int, int]]:
    """保留尺寸接近篆书单字的连续墨迹段。"""
    return [
        (start, end)
        for start, end in active_runs(gray, left, right)
        if 84 <= end - start <= 220
    ]


def baseline(occupied: dict[int, list[dict]], slot_runs: dict[int, list[tuple[int, int]]]) -> list[float]:
    """从已有、且确有大字墨迹的列提取同页共同纵向基线。"""
    values = []
    for slot, group in occupied.items():
        if len(slot_runs[slot]) < 2:
            continue
        values.extend((item["bbox"][1] + item["bbox"][3]) / 2 for item in group)
    values.sort()
    clusters: list[list[float]] = []
    for value in values:
        if not clusters or value - clusters[-1][-1] > 85:
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return [float(np.median(cluster)) for cluster in clusters if len(cluster) >= 2]


def row_match(runs: list[tuple[int, int]], rows: list[float]) -> float:
    if not runs or not rows:
        return 0.0
    centers = [(start + end) / 2 for start, end in runs]
    return sum(any(abs(center - row) < 85 for row in rows) for center in centers) / len(centers)


def baseline_coverage(runs: list[tuple[int, int]], rows: list[float]) -> float:
    """返回已有共同基线中，被候选槽大字覆盖的比例。

    不能只用 ``row_match``：候选列可能比同页其他列多出下半页的字，
    此时按候选行数作分母会把完全覆盖既有基线的真实缺列误降为低置信。
    """
    if not runs or not rows:
        return 0.0
    centers = [(start + end) / 2 for start, end in runs]
    return sum(any(abs(center - row) < 85 for center in centers) for row in rows) / len(rows)


def slot_score(runs: list[tuple[int, int]], match: float) -> float:
    """大字证据分；五行上下的规则篆书列得分最高。"""
    if len(runs) < 2:
        return 0.0
    heights = [end - start for start, end in runs]
    size = float(np.median(heights))
    height_score = max(0.0, 1.0 - abs(size - 125.0) / 85.0)
    count_score = min(1.0, len(runs) / 4.0)
    return round(0.45 * height_score + 0.25 * count_score + 0.30 * match, 3)


def main() -> None:
    parser = argparse.ArgumentParser(description="只读检查《说文广义》字框结构")
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start-page", type=int, required=True)
    parser.add_argument("--end-page", type=int, required=True)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--output", type=Path, help="同时把完整 JSON 审计报告写到此路径")
    args = parser.parse_args()

    extra_columns: list[dict] = []
    missing_columns: list[dict] = []
    missing_rows: list[dict] = []
    extra_rows: list[dict] = []
    page_summary: list[dict] = []

    for page in range(args.start_page, args.end_page + 1):
        image_path = args.work_dir / f"fatie-{page:04d}.webp"
        chars_path = args.work_dir / ".debug" / f"fatie-{page:04d}" / "chars.json"
        if not image_path.exists() or not chars_path.exists():
            continue
        gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        lines = grid_lines(gray)
        centers = [(left + right) / 2 for left, right in zip(lines, lines[1:])]
        items = json.loads(chars_path.read_text())
        columns = grouped(items)
        occupied: dict[int, list[dict]] = {}
        stored_by_slot: dict[int, list[int]] = defaultdict(list)
        unmapped: list[int] = []
        for stored, group in columns.items():
            slot = nearest_grid(group, centers)
            if slot is None:
                unmapped.append(stored)
            else:
                occupied.setdefault(slot, []).extend(group)
                stored_by_slot[slot].append(stored)
        runs = {
            index: seal_runs(gray, left, right)
            for index, (left, right) in enumerate(zip(lines, lines[1:]))
        }
        rows = baseline(occupied, runs)
        matches = {slot: row_match(slot_runs, rows) for slot, slot_runs in runs.items()}
        coverage = {slot: baseline_coverage(slot_runs, rows) for slot, slot_runs in runs.items()}
        scores = {slot: slot_score(slot_runs, matches[slot]) for slot, slot_runs in runs.items()}

        # 多列：两组不同 column 的框占据同一物理版格，保留框数较多的一组，
        # 其余组为重复/拆裂出来的候选。这个规则不依赖旧 column 的排序。
        collision_columns: set[int] = set()
        for slot, stored_columns in stored_by_slot.items():
            if len(stored_columns) < 2:
                continue
            survivor = max(stored_columns, key=lambda value: len(columns[value]))
            for stored in stored_columns:
                if stored == survivor:
                    continue
                collision_columns.add(stored)
                extra_columns.append({
                    "kind": "extra_column", "page": page, "stored_column": stored,
                    "grid_column": slot, "confidence": 0.90,
                    "evidence": "不同 column 的框占据同一物理版格，疑似重复或拆裂框列",
                })

        # 多框：已有框所在槽没有任何规范篆书墨迹，或与共同基线完全不匹配。
        for stored, group in columns.items():
            if stored in collision_columns:
                continue
            slot = nearest_grid(group, centers)
            if slot is None:
                extra_columns.append({
                    "kind": "extra_column", "page": page, "stored_column": stored,
                    "confidence": 0.95, "evidence": "框列无法映射到固定版格",
                })
                continue
            if len(runs[slot]) == 0 or (len(runs[slot]) < 2 and matches[slot] < 0.35):
                extra_columns.append({
                    "kind": "extra_column", "page": page, "stored_column": stored,
                    "grid_column": slot, "confidence": 0.95 if not runs[slot] else 0.82,
                    "evidence": "已有框槽没有成组篆书墨迹或不匹配共同基线",
                })

        # 少列：空槽内必须有至少两组大字，并且大多落在同页共同基线。
        # 当整页 ``chars.json`` 为空时，旧逻辑的共同基线也为空，因而会把
        # 明明整页有篆字的 0184 页当成“无可审计数据”。此时以同一固定版格
        # 内的多个、尺寸一致的大字段为直接证据，强制报出候选。
        for slot, slot_runs in runs.items():
            if slot in occupied or len(slot_runs) < 2:
                continue
            empty_page_evidence = not columns and scores[slot] >= 0.48
            baseline_evidence = max(matches[slot], coverage[slot]) >= 0.65 and scores[slot] >= 0.68
            if not empty_page_evidence and not baseline_evidence:
                continue
            missing_columns.append({
                "kind": "missing_column", "page": page, "grid_column": slot,
                "confidence": round(min(0.99, 0.50 + scores[slot] / 2), 2),
                "run_count": len(slot_runs),
                "row_match": round(matches[slot], 2),
                "baseline_coverage": round(coverage[slot], 2),
                "evidence": (
                    "整页无框但固定槽内有成组大字墨迹"
                    if empty_page_evidence else "空槽含成组大字墨迹，且与同页共同基线匹配"
                ),
            })

        # 少框：已有篆书列少了一个同页共同基线行。
        for stored, group in columns.items():
            slot = nearest_grid(group, centers)
            if slot is None or len(runs[slot]) < 2:
                continue
            frame_rows = [(item["bbox"][1] + item["bbox"][3]) / 2 for item in group]
            for start, end in runs[slot]:
                center = (start + end) / 2
                if any(abs(center - known) < 85 for known in frame_rows):
                    continue
                if any(abs(center - known) < 85 for known in rows):
                    missing_rows.append({
                        "kind": "missing_row", "page": page, "stored_column": stored,
                        "grid_column": slot, "y": round(center), "confidence": 0.82,
                        "evidence": "已有篆书列漏掉一条共同基线上的大字",
                    })

        # 多框行：排除已判为整列误框的列后，若一个框行附近完全没有
        # 对应的大字墨迹，则它是孤立的多框候选。不能只因为高度异常就删。
        extra_stored = {item["stored_column"] for item in extra_columns if item["page"] == page}
        for stored, group in columns.items():
            if stored in extra_stored:
                continue
            slot = nearest_grid(group, centers)
            if slot is None or len(runs[slot]) < 2:
                continue
            for item in group:
                center = (item["bbox"][1] + item["bbox"][3]) / 2
                if any(abs(center - (start + end) / 2) < 85 for start, end in runs[slot]):
                    continue
                extra_rows.append({
                    "kind": "extra_row", "page": page, "stored_column": stored,
                    "grid_column": slot, "y": round(center), "confidence": 0.82,
                    "evidence": "已有框行附近没有对应的规范篆书大字墨迹",
                })

        page_summary.append({
            "page": page,
            "physical_columns": len(columns),
            "grid_slots": len(centers),
            "unmapped_columns": unmapped,
        })

    report = {
        "range": [args.start_page, args.end_page],
        "extra_columns": extra_columns[:args.limit],
        "missing_columns": missing_columns[:args.limit],
        "missing_rows": missing_rows[:args.limit],
        "extra_rows": extra_rows[:args.limit],
        "totals": {
            "extra_columns": len(extra_columns),
            "missing_columns": len(missing_columns),
            "missing_rows": len(missing_rows),
            "extra_rows": len(extra_rows),
        },
        "pages": page_summary,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
