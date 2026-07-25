#!/usr/bin/env python3
"""向指定物理列追加人工确认的篆字框。"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path


def parse_frame(value: str) -> tuple[int, int, list[float]]:
    """解析 ``列号,行号,x1,y1,x2,y2``。"""
    parts = value.split(",")
    if len(parts) != 6:
        raise argparse.ArgumentTypeError("框应为 列号,行号,x1,y1,x2,y2")
    column, row = map(int, parts[:2])
    bbox = list(map(float, parts[2:]))
    if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise argparse.ArgumentTypeError("无效框坐标")
    return column, row, bbox


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("chars_json", type=Path)
    parser.add_argument("--char", required=True)
    parser.add_argument("--frame", type=parse_frame, action="append", required=True)
    args = parser.parse_args()

    entries = json.loads(args.chars_json.read_text())
    for column, row, bbox in args.frame:
        seeds = [item for item in entries if item.get("column") == column]
        if not seeds:
            raise ValueError(f"找不到列 {column}，无法继承元数据")
        seed = seeds[0]
        identifier = uuid.uuid4().hex
        entries.append({
            **{key: value for key, value in seed.items() if key not in {"id", "uuid", "char", "bbox", "column", "row"}},
            "id": identifier,
            "uuid": identifier,
            "char": args.char,
            "bbox": bbox,
            "column": column,
            "row": row,
        })
    args.chars_json.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
