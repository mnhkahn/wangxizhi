#!/usr/bin/env python3
"""从批处理前备份中恢复被误删、且原图中确有墨迹的篆书框。"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


def overlaps(entries: list[dict], candidate: dict) -> bool:
    x1, y1, x2, y2 = candidate["bbox"]
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    return any(
        abs((item["bbox"][0] + item["bbox"][2]) / 2 - cx) < 35
        and abs((item["bbox"][1] + item["bbox"][3]) / 2 - cy) < 85
        for item in entries
    )


def has_source_ink(gray: np.ndarray, bbox: list[int]) -> bool:
    x1, y1, x2, y2 = bbox
    width, height = x2 - x1, y2 - y1
    if not (35 <= width <= 140 and 55 <= height <= 280):
        return False
    crop = gray[max(0, y1):min(gray.shape[0], y2), max(0, x1):min(gray.shape[1], x2)]
    return crop.size > 0 and float(np.mean(crop < 170)) >= 0.08


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    page_count = 0
    restored_count = 0
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    for debug in sorted((args.work_dir / ".debug").glob("fatie-*")):
        chars = debug / "chars.json"
        backups = sorted((debug / "backups").glob("chars-before-volume-frames-20260802-*.json"))
        image_path = args.work_dir / f"{debug.name}.webp"
        if not chars.exists() or not backups or not image_path.exists():
            continue
        current = json.loads(chars.read_text())
        before = json.loads(backups[0].read_text())
        gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        additions = [
            item for item in before
            if not overlaps(current, item) and has_source_ink(gray, item["bbox"])
        ]
        if not additions:
            continue
        page_count += 1
        restored_count += len(additions)
        if not args.apply:
            print(f"{debug.name}: 可恢复 {len(additions)}")
            continue
        backups_dir = debug / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(chars, backups_dir / f"chars-before-source-restore-{stamp}.json")
        entries = current + additions
        columns = sorted({int(item.get("column", item.get("col", 0))) for item in entries})
        for column in columns:
            members = sorted(
                (item for item in entries if int(item.get("column", item.get("col", 0))) == column),
                key=lambda item: (item["bbox"][1] + item["bbox"][3]) / 2,
            )
            for row, item in enumerate(members):
                item["row"] = row
        entries.sort(key=lambda item: (-int(item.get("column", item.get("col", 0))), item["row"]))
        chars.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")
    print(f"{'恢复' if args.apply else '检出'} {page_count} 页，共 {restored_count} 个框")


if __name__ == "__main__":
    main()
