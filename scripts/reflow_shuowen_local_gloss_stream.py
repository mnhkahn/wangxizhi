#!/usr/bin/env python3
"""用本地《史典》顺序和本地《说文》释义对照，重排已有框的标签。"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path


VARIANTS = str.maketrans({
    "從": "从", "爲": "为", "為": "为", "聲": "声", "讀": "读",
    "與": "与", "書": "书", "說": "说", "擊": "击", "雲": "云",
    "實": "实", "內": "内", "兒": "儿", "爾": "尔", "無": "无",
    "變": "变", "餘": "余", "會": "会", "當": "当", "舉": "举",
    "長": "长", "開": "开", "閉": "闭", "齊": "齐", "聿": "书",
})


def normalized(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "").translate(VARIANTS)
    return "".join(char for char in value if "\u3400" <= char <= "\U0003134f")


def physical_slots(work_dir: Path, start_page: int) -> tuple[list[tuple[int, int]], dict[int, tuple[Path, list[dict]]]]:
    slots: list[tuple[int, int]] = []
    pages: dict[int, tuple[Path, list[dict]]] = {}
    for path in sorted((work_dir / ".debug").glob("fatie-*/chars.json")):
        page = int(path.parent.name.removeprefix("fatie-"))
        if page < start_page:
            continue
        items = json.loads(path.read_text())
        groups: dict[int, list[dict]] = {}
        for item in items:
            column = item.get("column", item.get("col"))
            if isinstance(column, int):
                groups.setdefault(column, []).append(item)
        for column, group in sorted(
            groups.items(),
            key=lambda pair: sum((x["bbox"][0] + x["bbox"][2]) / 2 for x in pair[1]) / len(pair[1]),
            reverse=True,
        ):
            slots.append((page, column))
        pages[page] = (path, items)
    return slots, pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start-page", type=int, required=True)
    parser.add_argument("--start-source-entry", type=int, required=True)
    parser.add_argument("--allow-unresolved-duplicates", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    entries = json.loads((args.work_dir / "shidian-glosses.json").read_text())["entries"]
    rules_path = args.work_dir / "shidian-gloss-resolutions.json"
    rules = json.loads(rules_path.read_text())["entries"] if rules_path.exists() else {}
    reference = json.loads((args.work_dir / "ctext-shuowen-reference.json").read_text())["entries"]
    reference_glosses = [(item["headword"], normalized(item["gloss"])) for item in reference]

    labels: list[dict] = []
    for index, entry in enumerate(entries, 1):
        if index < args.start_source_entry:
            continue
        rule = rules.get(str(index), {})
        if rule.get("kind") == "continuation":
            continue
        raw = str(rule.get("char", entry.get("headword", ""))).strip()
        text = normalized(str(entry.get("gloss", "")))
        scores = sorted(
            ((SequenceMatcher(None, text, gloss).ratio(), char) for char, gloss in reference_glosses),
            reverse=True,
        )
        score, matched = scores[0]
        second = scores[1][0] if len(scores) > 1 else 0.0
        # 显式覆写优先：这是人工根据原书/可靠对照确认的真实字头。
        if rule.get("kind") == "headword":
            char, mode = raw, "manual_resolution"
        # 释义的唯一高匹配优先于 OCR 字头；其余保留单字字头，避免猜测。
        elif score >= 0.72 and score - second >= 0.08:
            char, mode = matched, "local_reference"
        elif len(raw) == 1:
            char, mode = raw, "shidian_single"
        elif score >= 0.60 and score - second >= 0.06:
            char, mode = matched, "local_reference_relaxed"
        else:
            # 该情形是 OCR 重复字头且本地参考尚未覆盖的尾部；保留一个字位，
            # 不会凭空删除条目或拼接为多字标签。
            char, mode = raw[0], "repeated_ocr_fallback"
        if len(char) != 1:
            raise ValueError(f"第 {index} 条无法产生单字标签：{char!r}")
        labels.append({"source_entry": index, "char": char, "mode": mode, "score": round(score, 3)})

    slots, pages = physical_slots(args.work_dir, args.start_page)
    if len(labels) < len(slots):
        raise ValueError(f"本地释文仅 {len(labels)} 字，物理列有 {len(slots)} 个")
    assignments = [dict(page=page, column=column, **label) for (page, column), label in zip(slots, labels)]
    duplicates = []
    by_page: dict[int, list[dict]] = {}
    for assignment in assignments:
        by_page.setdefault(assignment["page"], []).append(assignment)
    for page, page_assignments in by_page.items():
        for right, left in zip(page_assignments, page_assignments[1:]):
            if right["char"] == left["char"]:
                duplicates.append({"page": page, "right_column": right["column"], "left_column": left["column"], "char": right["char"], "source_entries": [right["source_entry"], left["source_entry"]]})
    if duplicates:
        duplicate_path = args.work_dir / f"local-gloss-duplicate-candidates-{args.start_page:04d}.json"
        duplicate_path.write_text(json.dumps(duplicates, ensure_ascii=False, indent=2) + "\n")
        if not args.allow_unresolved_duplicates:
            raise ValueError("顺排后出现相邻重复释文，先解析来源条目：" + json.dumps(duplicates[:20], ensure_ascii=False))
    summary = {
        "start_page": args.start_page,
        "start_source_entry": args.start_source_entry,
        "slots": len(slots),
        "labels_available": len(labels),
        "modes": {mode: sum(x["mode"] == mode for x in assignments) for mode in sorted({x["mode"] for x in assignments})},
        "unresolved_adjacent_duplicates": duplicates,
        "assignments": assignments,
    }
    print(json.dumps({key: value for key, value in summary.items() if key != "assignments"}, ensure_ascii=False))
    if not args.apply:
        return
    for item in assignments:
        _, rows = pages[item["page"]]
        for row in rows:
            if row.get("column", row.get("col")) == item["column"]:
                row["char"] = item["char"]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path, rows in pages.values():
        backup = path.parent / "backups"
        backup.mkdir(exist_ok=True)
        shutil.copy2(path, backup / f"chars-before-local-gloss-reflow-{stamp}.json")
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    output = args.work_dir / f"local-gloss-reflow-{args.start_page:04d}.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(f"已写入：{output}")


if __name__ == "__main__":
    main()
