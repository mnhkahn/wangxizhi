#!/usr/bin/env python3
"""以指定列和统一行基线重建单页《说文广义》字框。

适用于墨迹与释文粘连、自动投影不能可靠切行的个别页。只替换目标页的
框坐标/行号；每个物理列的已有 ``char`` 会原样继承，绝不重排释文流。
默认仅预览，``--apply`` 才会写入，并自动备份原 ``chars.json``。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent))
from frame_shuowen_volume import grid_lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("page", type=int)
    parser.add_argument("--columns", help="从页面左侧网格数的列号，如 2,4,6,8")
    parser.add_argument("--row-centers", help="统一行中心，如 465,641,818")
    parser.add_argument(
        "--column-rows",
        help="按列指定真实行中心，例如 '1:520,700;3:510,690,870'；用于各列字数不等的页。",
    )
    parser.add_argument(
        "--x-overrides",
        help="指定列的框左边界，例如 '2:170'；用于版线检测偏移的页。",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if bool(args.column_rows) == bool(args.columns or args.row_centers):
        raise ValueError("请使用 --column-rows，或同时提供 --columns 与 --row-centers")
    if args.column_rows:
        layout = {
            int(partition.split(":", 1)[0]): [int(value) for value in partition.split(":", 1)[1].split(",")]
            for partition in args.column_rows.split(";")
        }
    else:
        columns = [int(value) for value in args.columns.split(",")]
        rows = [int(value) for value in args.row_centers.split(",")]
        layout = {column: rows for column in columns}
    x_overrides = ({
        int(partition.split(":", 1)[0]): int(partition.split(":", 1)[1])
        for partition in args.x_overrides.split(",")
    } if args.x_overrides else {})
    image_path = args.work_dir / f"fatie-{args.page:04d}.webp"
    chars_path = args.work_dir / ".debug" / image_path.stem / "chars.json"
    image = cv2.imread(str(image_path))
    if image is None or not chars_path.exists():
        raise FileNotFoundError(image_path if image is None else chars_path)
    old = json.loads(chars_path.read_text())
    old_groups: dict[int, list[dict]] = defaultdict(list)
    for item in old:
        column = item.get("column", item.get("col"))
        if isinstance(column, int):
            old_groups[column].append(item)
    labels = {column: values[0].get("char", "") for column, values in old_groups.items()}
    lines = grid_lines(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
    rebuilt: list[dict] = []
    for column, column_rows in layout.items():
        if column >= len(lines) - 1:
            raise ValueError(f"网格列 {column} 超出页面范围")
        left, right = lines[column], lines[column + 1]
        width = min(104, right - left - 20)
        x1 = x_overrides.get(column, int(round((left + right - width) / 2)))
        x2 = x1 + width
        label = labels.get(column, "")
        for row, center in enumerate(column_rows):
            identifier = uuid.uuid4().hex
            rebuilt.append({
                "id": identifier, "uuid": identifier, "char": label, "font": "篆书",
                "author": "程德洽", "work": args.work_dir.name.removeprefix("程德洽-篆书-"),
                "work_dir": str(args.work_dir), "bbox": [x1, center - 64, x2, center + 64],
                "column": column, "row": row, "visible": True,
            })
    preview = image.copy()
    for item in rebuilt:
        x1, y1, x2, y2 = item["bbox"]
        cv2.rectangle(preview, (x1, y1), (x2, y2), (0, 220, 0), 4)
    preview_path = chars_path.parent / "fixed-grid-preview.jpg"
    cv2.imwrite(str(preview_path), preview)
    print(f"预览：{preview_path}；{len(layout)} 列、共 {len(rebuilt)} 框")
    if not args.apply:
        return
    backup = chars_path.parent / "backups"
    backup.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(chars_path, backup / f"chars-before-fixed-grid-{stamp}.json")
    chars_path.write_text(json.dumps(rebuilt, ensure_ascii=False, indent=2) + "\n")
    print(f"已写入：{chars_path}")


if __name__ == "__main__":
    main()
