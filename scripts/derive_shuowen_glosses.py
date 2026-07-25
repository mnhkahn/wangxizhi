#!/usr/bin/env python3
"""从项目 OCR 的整页结果提取每个篆书列对应的释文首字。

篆书列在版面阅读方向的右侧为相邻释文格。一个释文格可能有两条竖排文字：
只取更贴近篆书列的一条，另一条声训过滤。右页最左列跨书脊连接左页末格。
本脚本只生成标签清单，不修改 chars.json。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def chinese(text: str) -> str:
    return "".join(char for char in text if "一" <= char <= "鿿")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("grid", type=Path)
    parser.add_argument("proposals", type=Path)
    parser.add_argument("ocr_result", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    grid = json.loads(args.grid.read_text())
    proposals = json.loads(args.proposals.read_text())
    ocr = json.loads(args.ocr_result.read_text())
    cells = {(item["page"], item["column"]): item["bbox"] for item in grid["columns"]}
    seal_cells = sorted({(item["page"], item["grid_column"]) for item in proposals})
    labels: list[dict[str, object]] = []

    for page, seal_column in seal_cells:
        target = (page, seal_column - 1) if seal_column else (page - 1, 9)
        target_bbox = cells[target]
        candidates: list[tuple[float, str, list[float]]] = []
        for entry in ocr["parsed_results"]:
            text = chinese(entry.get("text", ""))
            bbox = entry.get("bbox", [0, 0, 0, 0])
            center_x = (bbox[0] + bbox[2]) / 2
            if text and target_bbox[0] <= center_x <= target_bbox[2] and bbox[1] >= 1000:
                candidates.append((bbox[0], text, bbox))
        # x 最大的一条最贴近该篆书列；其余（如“某聲某切”）不作为释文。
        candidates.sort(reverse=True)
        selected = candidates[0] if candidates else None
        labels.append({
            "page": page,
            "seal_grid_column": seal_column,
            "char": selected[1][0] if selected else "",
            "source_text": selected[1] if selected else "",
            "source_bbox": selected[2] if selected else [],
            "ignored_texts": [item[1] for item in candidates[1:]],
        })

    args.output.write_text(json.dumps(labels, ensure_ascii=False, indent=2) + "\n")
    for item in labels:
        print(f"page={item['page']} seal={item['seal_grid_column']}: {item['char']} ← {item['source_text']}")


if __name__ == "__main__":
    main()
