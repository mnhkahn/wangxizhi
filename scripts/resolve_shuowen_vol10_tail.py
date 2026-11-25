#!/usr/bin/env python3
"""补全卷十第 149 页以后《史典》断行字头的人工校勘表。

这些条目逐条以公开《说文解字》规范释文核对；续文不占篆字槽。
本脚本只写 ``shidian-gloss-resolutions.json``，不触碰任何框或标签。
"""

from __future__ import annotations

import argparse
import glob
import json
import shutil
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher
import re


# entry -> correct single-character headword.  The remaining repeated-line
# entries in the review report are confirmed continuations.
HEADWORDS = {
    644: "眅", 649: "瞗", 665: "眂", 668: "瞽", 671: "眕", 672: "𥆵", 675: "䁔",
    704: "眮",
    875: "䏽",
    894: "𢿱",
    929: "腌",
    1292: "㻸",
    1293: "琛",
    1297: "琫",
    1301: "𤣱",
    1318: "𤨏",
    1325: "珣",
    1332: "𤥟",
    1336: "𤧩",
    1353: "璓",
    1361: "𤩰",
    1362: "瑟",
    1363: "𤥜",
    1369: "𤩚",
    679: "睅", 685: "睍", 691: "𥌡", 698: "矘", 701: "瞫",
    724: "眛", 728: "瞚", 729: "睴", 730: "矔", 748: "睦",
    751: "眜", 752: "䁊", 762: "矆", 763: "䀩", 767: "𥉈",
    769: "眔", 806: "脧", 960: "竿", 966: "𥸅", 1025: "管",
    1047: "笥", 1085: "簙", 1095: "籋", 1217: "𤔱", 1219: "㻃",
    1246: "璡", 1289: "瑬", 1320: "璗",
}

# OCR 把释文残片识别成字头；这些条目绝不占字槽。
FORCED_CONTINUATIONS = {856, 930, 965, 1094, 1319}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument(
        "--reference-dir", type=Path,
        help="公开 shuowenjiezi/shuowen 的 data 目录；用于补 OCR 多字头。",
    )
    parser.add_argument(
        "--canonicalize-all", action="store_true",
        help="以同释文的规范字头覆写本段所有非续行 OCR 字头。",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    report = args.work_dir / "shidian-unresolved-headwords-0641.json"
    pending = {item["entry"] for item in json.loads(report.read_text())}
    rules = {
        str(entry): (
            {"kind": "headword", "char": HEADWORDS[entry],
             "note": "以公开《说文解字》规范释文逐条核对的断行字头。"}
            if entry in HEADWORDS else
            {"kind": "continuation",
             "note": "同一释文的 OCR 续行，不占篆字槽。"}
        )
        for entry in sorted(pending)
    }
    if args.reference_dir:
        source = json.loads((args.work_dir / "shidian-glosses.json").read_text())["entries"]
        existing = json.loads((args.work_dir / "shidian-gloss-resolutions.json").read_text()).get("entries", {})

        def normalise(text: str) -> str:
            return re.sub(r"[^\u3400-\u9fff\U00020000-\U0002ffff]", "", text)

        records = []
        for filename in glob.glob(str(args.reference_dir / "*.json")):
            item = json.loads(Path(filename).read_text())
            records.append((item["wordhead"], normalise(item["explanation"]), item["radical"]))

        def radical_for(entry: int) -> str | None:
            if entry <= 772:
                return "目"
            if entry <= 774:
                return "尗"
            if entry <= 929:
                return "肉"
            if entry == 930:
                return "艸"
            if entry <= 1097:
                return "竹"
            if entry == 1098:
                return "六"
            if entry in (1099, 1100):
                return "𦥑"
            if entry <= 1103:
                return "菐"
            if entry == 1104:
                return "菐"
            if entry <= 1109:
                return "束"
            if entry <= 1111:
                return "蓐"
            if entry <= 1213:
                return "足"
            if entry <= 1219:
                return "曲"
            return "玉"

        manual = {
            759: "𥋚", 1101: "菐", 1103: "𠔯", 1104: "僕",
            1105: "束", 1106: "柬", 1107: "𢆞", 1108: "剌",
            1372: "𤨙",
        }
        auto_count = 0
        for entry, item in enumerate(source, 1):
            if entry < 641:
                continue
            if entry in FORCED_CONTINUATIONS:
                rules[str(entry)] = {
                    "kind": "continuation",
                    "note": "原图无独立篆字；OCR 将释文残片误作字头。",
                }
                continue
            prior = rules.get(str(entry)) or existing.get(str(entry))
            if entry not in HEADWORDS and prior and prior.get("kind") == "continuation":
                continue
            raw = item.get("headword")
            if not args.canonicalize_all and (str(entry) in existing or str(entry) in rules):
                continue
            if not args.canonicalize_all and isinstance(raw, str) and len(raw) == 1:
                continue
            if entry in HEADWORDS:
                char = HEADWORDS[entry]
            elif entry in manual:
                char = manual[entry]
            else:
                gloss = normalise(item.get("gloss", ""))
                pool = [x for x in records if x[2] == radical_for(entry)]
                def score(candidate: tuple[str, str, str]) -> float:
                    _, explanation, _ = candidate
                    matcher = SequenceMatcher(None, gloss, explanation)
                    longest = matcher.find_longest_match().size
                    return longest * 2 / (len(gloss) + len(explanation)) + .25 * matcher.ratio()
                char = max(pool, key=score)[0]
            rules[str(entry)] = {
                "kind": "headword", "char": char,
                "note": "按公开《说文解字》同释文回填的规范字头，供卷十尾段顺排使用。",
            }
            auto_count += 1
        print(f"另补 {auto_count} 条 OCR 多字头")
    print(f"将写入 {len(rules)} 条：{len(HEADWORDS)} 个字头，{len(rules)-len(HEADWORDS)} 条续文")
    if not args.apply:
        return

    path = args.work_dir / "shidian-gloss-resolutions.json"
    data = json.loads(path.read_text())
    backup = path.with_name(f"{path.stem}-before-vol10-tail-{datetime.now():%Y%m%d-%H%M%S}.json")
    shutil.copy2(path, backup)
    data.setdefault("entries", {}).update(rules)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"已写入：{path}；备份：{backup}")


if __name__ == "__main__":
    main()
