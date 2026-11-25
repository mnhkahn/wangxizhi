#!/usr/bin/env python3
"""按 Col 修复同页重复释文，并把后续释文依次前移。

规则：
1. 页面从小到大处理；同页按 column 从大到小（从右到左）处理。
2. 一个 column 是一个释文槽位，列内所有框使用同一个字。
3. 同一页不同 column 出现相同非空释文时，仅保留第一次出现的释文流项。
4. 去重后的释文流重新写回全部 column 槽位；不修改坐标、行号或列号。
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("volume", type=Path, help="字帖目录")
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="实际写入；默认仅预览")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    debug_dir = args.volume / ".debug"
    pages: list[tuple[int, Path, list[dict]]] = []
    slots: list[tuple[int, int, list[dict]]] = []

    for page in range(args.start, args.end + 1):
        path = debug_dir / f"fatie-{page:04d}" / "chars.json"
        if not path.exists():
            continue
        chars = json.loads(path.read_text(encoding="utf-8"))
        pages.append((page, path, chars))
        groups: dict[int, list[dict]] = defaultdict(list)
        for item in chars:
            column = item.get("column")
            if isinstance(column, int):
                groups[column].append(item)

        for column in sorted(groups, reverse=True):
            group = groups[column]
            slots.append((page, column, group))

    changed_pages: set[int] = set()
    all_duplicates: list[tuple[int, int, str]] = []
    pass_count = 0
    while True:
        source: list[str] = []
        duplicates: list[tuple[int, int, str]] = []
        current_page = -1
        seen: set[str] = set()
        for page, column, group in slots:
            if page != current_page:
                current_page = page
                seen = set()
            char = next((str(x.get("char", "")) for x in group if x.get("char")), "")
            if not char:
                continue
            if char in seen:
                duplicates.append((page, column, char))
                continue
            seen.add(char)
            source.append(char)

        if not duplicates:
            break
        pass_count += 1
        all_duplicates.extend(duplicates)
        new_labels = source + [""] * (len(slots) - len(source))
        for (page, _column, group), char in zip(slots, new_labels):
            if any(item.get("char", "") != char for item in group):
                changed_pages.add(page)
            for item in group:
                item["char"] = char

    print(
        f"slots={len(slots)} source={len(source)} "
        f"duplicates={len(all_duplicates)} passes={pass_count}"
    )
    for page, column, char in all_duplicates:
        print(f"duplicate page={page:04d} col={column} char={char}")
    print("changed_pages=" + ",".join(f"{p:04d}" for p in sorted(changed_pages)))

    if not args.apply:
        return

    stamp = datetime.now().strftime("col-dedup-%Y%m%d-%H%M%S")
    for page, path, chars in pages:
        if page not in changed_pages:
            continue
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        shutil.copy2(path, backup_dir / f"chars.{stamp}.json")
        path.write_text(
            json.dumps(chars, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"backup={stamp}")


if __name__ == "__main__":
    main()
