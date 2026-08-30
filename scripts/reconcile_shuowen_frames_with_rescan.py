#!/usr/bin/env python3
"""用已生成的 seal-proposals 清理多余/重叠框，保留已有单字标签。

此脚本不新增框、不改 bbox 或 column。它只保留能和本页重扫篆字框一对一
匹配的既有框；未匹配者是空框、释文误框或同位重叠框候选。写入前逐页备份。
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def centre(item: dict) -> tuple[float, float]:
    x1, y1, x2, y2 = item["bbox"]
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--pages", required=True, help="逗号分隔的页码")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    page_numbers = [int(value) for value in args.pages.split(",") if value.strip()]

    plan: dict[int, tuple[Path, list[dict], list[dict], list[dict]]] = {}
    summary = []
    for page in page_numbers:
        debug = args.work_dir / ".debug" / f"fatie-{page:04d}"
        chars_path = debug / "chars.json"
        proposals_path = debug / "seal-proposals.json"
        existing = json.loads(chars_path.read_text(encoding="utf-8"))
        proposals = json.loads(proposals_path.read_text(encoding="utf-8"))
        available = set(range(len(proposals)))
        kept: list[dict] = []
        removed: list[dict] = []

        # 先按纵向顺序匹配，避免一个重叠旧框同时占用同一个重扫框。
        for item in sorted(existing, key=lambda value: (value.get("column", value.get("col", -1)), centre(value)[1])):
            column = item.get("column", item.get("col"))
            if not isinstance(column, int):
                removed.append(item)
                continue
            x, y = centre(item)
            choices = []
            for index in available:
                proposal = proposals[index]
                if int(proposal["column"]) != column:
                    continue
                px, py = centre(proposal)
                if abs(x - px) <= 60 and abs(y - py) <= 110:
                    choices.append((abs(x - px) * 2 + abs(y - py), index))
            if not choices:
                removed.append(item)
                continue
            _, index = min(choices)
            available.remove(index)
            kept.append(dict(item))

        for column in sorted({item.get("column", item.get("col")) for item in kept if isinstance(item.get("column", item.get("col")), int)}):
            rows = sorted(
                (item for item in kept if item.get("column", item.get("col")) == column),
                key=lambda item: centre(item)[1],
            )
            for row, item in enumerate(rows):
                item["row"] = row
        kept.sort(key=lambda item: (-int(item.get("column", item.get("col", -1))), int(item.get("row", 0))))

        plan[page] = (chars_path, existing, kept, removed)
        summary.append({
            "page": page,
            "before": len(existing),
            "rescan_boxes": len(proposals),
            "kept": len(kept),
            "removed": len(removed),
            "removed_frames": [
                {
                    "column": item.get("column", item.get("col")),
                    "row": item.get("row"),
                    "char": item.get("char", ""),
                    "bbox": item["bbox"],
                }
                for item in removed
            ],
        })

    print(json.dumps({"pages": summary}, ensure_ascii=False, indent=2))
    if not args.apply:
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for page, (path, _, kept, _) in plan.items():
        backup = path.parent / "backups"
        backup.mkdir(exist_ok=True)
        shutil.copy2(path, backup / f"chars-before-rescan-reconcile-{stamp}.json")
        path.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit = args.work_dir / f"rescan-frame-reconcile-{stamp}.json"
    audit.write_text(json.dumps({"pages": summary}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入；审计：{audit}")


if __name__ == "__main__":
    main()
