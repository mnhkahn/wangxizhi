#!/usr/bin/env python3
"""将指定页当前 chars.json 的框与列号叠加到原图，供人工核对。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("page", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    image = args.work_dir / f"fatie-{args.page:04d}.webp"
    chars = args.work_dir / ".debug" / f"fatie-{args.page:04d}" / "chars.json"
    canvas = cv2.imread(str(image), cv2.IMREAD_COLOR)
    if canvas is None:
        raise FileNotFoundError(image)
    for item in json.loads(chars.read_text()):
        x1, y1, x2, y2 = item["bbox"]
        column, row = item["column"], item["row"]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 220, 0), 3)
        cv2.putText(canvas, f"{column}/{row}", (x1 + 2, max(26, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 230), 2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output), canvas)


if __name__ == "__main__":
    main()
