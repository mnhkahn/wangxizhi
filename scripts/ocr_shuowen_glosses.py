#!/usr/bin/env python3
"""识别《说文广义》篆书列右侧释文列的首字。

输入是按竖线切列后的 columns.json 和 seal-proposals.json。双栏释文会被跳过；
结果先写入独立 gloss-ocr.json，默认不改 chars.json。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

# 允许从 scripts/ 直接运行，并仍复用项目内已配置 Token 的 OCR 模块。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ocr.api_client import OCRAPIClient
from ocr.recognizer import CalligraphyOCR


def lane_count(image: np.ndarray, x1: int, x2: int) -> int:
    """估计顶部释文区的并列文字栏数，用于跳过双栏释文。"""
    ink = (image[1120:1850, x1 + 15:x2 - 15] < 105).sum(axis=0) >= 4
    for _ in range(12):
        ink[1:-1] |= ink[:-2] & ink[2:]
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for index, active in enumerate(ink):
        if active and start is None:
            start = index
        if start is not None and (not active or index == len(ink) - 1):
            end = index if not active else index + 1
            if end - start > 20:
                spans.append((start, end))
            start = None
    return len(spans)


def first_chinese_char(api_result: dict) -> str:
    """从项目 OCR 的 spotting 结果中取最靠上的汉字。"""
    parser = CalligraphyOCR()
    entries = parser._parse_markdown_result(api_result)
    candidates: list[tuple[float, float, str]] = []
    for entry in entries:
        text = "".join(char for char in entry.get("text", "") if "\u4e00" <= char <= "\u9fff")
        if not text:
            continue
        bbox = entry.get("bbox", [0, 0, 0, 0])
        candidates.append((float(bbox[1]), float(bbox[0]), text[0]))
    return sorted(candidates)[0][2] if candidates else ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("grid", type=Path)
    parser.add_argument("proposals", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--crops", type=Path, required=True)
    args = parser.parse_args()

    image = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(args.image)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    grid = json.loads(args.grid.read_text())
    proposals = json.loads(args.proposals.read_text())
    cells = {(item["page"], item["column"]): item["bbox"] for item in grid["columns"]}
    keys = sorted({(item["page"], item["grid_column"]) for item in proposals})
    args.crops.mkdir(parents=True, exist_ok=True)
    client = OCRAPIClient()
    rows: list[dict[str, object]] = []

    for page, seal_column in keys:
        # 视觉上的右侧一列：扫描图中 x 更大的下一网格列。
        gloss_bbox = cells.get((page, seal_column + 1))
        if gloss_bbox is None:
            continue
        x1, _, x2, _ = map(int, gloss_bbox)
        lanes = lane_count(gray, x1, x2)
        row: dict[str, object] = {
            "page": page,
            "seal_grid_column": seal_column,
            "gloss_grid_column": seal_column + 1,
            "lanes": lanes,
            "char": "",
        }
        if lanes >= 2:
            row["skipped"] = "two_text_lanes"
            rows.append(row)
            continue

        crop_path = args.crops / f"page-{page}-seal-{seal_column:02d}-gloss.jpg"
        crop = image[1080:1900, x1 + 15:x2 - 15]
        cv2.imwrite(str(crop_path), crop)
        try:
            api_result = client.recognize(str(crop_path))
            row["char"] = first_chinese_char(api_result)
        except Exception as error:
            row["error"] = str(error)
        row["crop"] = str(crop_path)
        rows.append(row)
        print(f"page={page} seal={seal_column}: {row['char'] or row.get('error', 'empty')}")

    args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    print(f"输出：{args.output}")


if __name__ == "__main__":
    main()
