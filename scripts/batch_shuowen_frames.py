#!/usr/bin/env python3
"""仅批量生成《说文广义》篆字框；不调用 OCR，也不改已有 chars.json。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extract_shuowen_grid import page_boundaries
from propose_shuowen_seal_boxes import proposal_boxes_by_gaps


def entries_from_proposals(proposals: list[dict], work_dir: Path) -> list[dict]:
    """复用桌面版 chars.json 格式，释文字段保持空白。"""
    import uuid

    entries = []
    for row, proposal in enumerate(proposals):
        identifier = uuid.uuid4().hex
        entries.append({
            "id": identifier, "uuid": identifier, "char": "", "font": "篆书",
            "author": "程德洽", "work": "说文广义-高清", "work_dir": str(work_dir),
            "bbox": proposal["bbox"],
            "column": int(proposal["page"]) * 100 + int(proposal["grid_column"]),
            "row": row, "visible": True,
        })
    return entries


def process(work_dir: Path, number: int) -> str:
    image_path = work_dir / f"fatie-{number:03d}.jpg"
    debug_dir = work_dir / ".debug" / image_path.stem
    chars_path = debug_dir / "chars.json"
    if chars_path.exists():
        return "跳过（已有框）"
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(image_path)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    pages = page_boundaries(gray)
    columns = []
    for page, boundaries in enumerate(pages):
        for column, (x1, x2) in enumerate(zip(boundaries, boundaries[1:])):
            columns.append({"page": page, "column": column, "bbox": [x1, 0, x2, image.shape[0]]})
    manifest = {"source": str(image_path), "pages": pages, "columns": columns}
    proposals = proposal_boxes_by_gaps(gray, manifest)
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "seal-proposals.json").write_text(json.dumps(proposals, ensure_ascii=False, indent=2) + "\n")
    chars_path.write_text(json.dumps(entries_from_proposals(proposals, work_dir), ensure_ascii=False, indent=2) + "\n")
    preview = image.copy()
    for proposal in proposals:
        x1, y1, x2, y2 = map(int, proposal["bbox"])
        cv2.rectangle(preview, (x1, y1), (x2, y2), (0, 0, 255), 12)
    cv2.imwrite(str(debug_dir / "seal-proposals-preview.jpg"), preview)
    return f"{len(proposals)} 框"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start", type=int, default=41)
    parser.add_argument("--end", type=int, default=87)
    args = parser.parse_args()
    for number in range(args.start, args.end + 1):
        print(f"fatie-{number:03d}: {process(args.work_dir, number)}", flush=True)


if __name__ == "__main__":
    main()
