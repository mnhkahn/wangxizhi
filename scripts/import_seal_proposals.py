#!/usr/bin/env python3
"""将已核验的篆书候选框导入桌面版读取的 chars.json。"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("proposals", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", required=True)
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError(f"为保护人工标注，拒绝覆盖：{args.output}")
    proposals = json.loads(args.proposals.read_text())
    entries = []
    for index, proposal in enumerate(proposals):
        identifier = uuid.uuid4().hex
        entries.append({
            "id": identifier,
            "uuid": identifier,
            "char": "",
            "font": "篆书",
            "author": "程德洽",
            "work": "说文广义-高清",
            "work_dir": args.work_dir,
            "bbox": proposal["bbox"],
            "column": proposal["page"] * 100 + proposal["grid_column"],
            "row": index,
            "visible": True,
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")
    print(f"写入 {len(entries)} 个篆书框：{args.output}")


if __name__ == "__main__":
    main()
