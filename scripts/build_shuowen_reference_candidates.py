#!/usr/bin/env python3
"""以《史典》释文正文匹配本地《说文解字》对照库，生成可复查候选表。

只生成候选 JSON，绝不改 chars.json 或校勘表。OCR 字头不作为匹配依据。
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path


VARIANTS = str.maketrans({
    "從": "从", "爲": "为", "為": "为", "聲": "声", "讀": "读",
    "與": "与", "說": "说", "書": "书", "舉": "举", "長": "长",
    "餘": "余", "會": "会", "當": "当", "齊": "齐", "實": "实",
    "內": "内", "兒": "儿", "無": "无", "變": "变", "開": "开",
    "閉": "闭", "畫": "画", "爾": "尔", "雲": "云", "風": "风",
})


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").translate(VARIANTS)
    return "".join(char for char in value if "\u3400" <= char <= "\U0003134f")


def score(left: str, right: str) -> tuple[float, float, float]:
    matcher = SequenceMatcher(None, left, right, autojunk=False)
    ratio = matcher.ratio()
    longest = matcher.find_longest_match().size * 2 / max(1, len(left) + len(right))
    return round(ratio * 0.55 + longest * 0.45, 4), round(ratio, 4), round(longest, 4)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("reference_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    source = json.loads((args.work_dir / "shidian-glosses.json").read_text())["entries"]
    reference = []
    for filename in glob.glob(str(args.reference_dir / "*.json")):
        record = json.loads(Path(filename).read_text())
        headword = str(record.get("wordhead", ""))
        explanation = normalize(str(record.get("explanation", "")))
        if len(headword) == 1 and explanation:
            reference.append({
                "id": record.get("id"), "char": headword,
                "radical": record.get("radical", ""), "text": explanation,
            })
    if not reference:
        raise ValueError("对照库中没有可用条目")

    index: dict[str, set[int]] = defaultdict(set)
    for number, record in enumerate(reference):
        text = record["text"]
        for offset in range(max(0, len(text) - 2)):
            index[text[offset:offset + 3]].add(number)

    results = []
    for source_entry, entry in enumerate(source, 1):
        text = normalize(str(entry.get("gloss", "")))
        votes: Counter[int] = Counter()
        for offset in range(max(0, len(text) - 2)):
            votes.update(index.get(text[offset:offset + 3], ()))
        candidates = [number for number, _ in votes.most_common(48)]
        if not candidates:
            candidates = list(range(len(reference)))
        ranked = []
        for number in candidates:
            total, ratio, longest = score(text, reference[number]["text"])
            ranked.append((total, ratio, longest, number))
        ranked.sort(reverse=True)
        choices = []
        for total, ratio, longest, number in ranked[:3]:
            ref = reference[number]
            choices.append({
                "reference_id": ref["id"], "char": ref["char"], "radical": ref["radical"],
                "score": total, "ratio": ratio, "longest_overlap": longest,
            })
        best = choices[0]
        second = choices[1]["score"] if len(choices) > 1 else 0.0
        confidence = (
            "high" if best["score"] >= 0.73 and best["score"] - second >= 0.05
            else "review" if best["score"] >= 0.56
            else "low"
        )
        results.append({
            "source_entry": source_entry,
            "ocr_headword": entry.get("headword", ""),
            "gloss": entry.get("gloss", ""),
            "candidate": best,
            "alternatives": choices[1:],
            "confidence": confidence,
        })

    output = args.output or args.work_dir / "shuowen-reference-candidates.json"
    summary = Counter(item["confidence"] for item in results)
    output.write_text(json.dumps({
        "source": "shidian-glosses.json",
        "reference": str(args.reference_dir),
        "entries": results,
        "summary": dict(summary),
    }, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(output), "reference_entries": len(reference), **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
