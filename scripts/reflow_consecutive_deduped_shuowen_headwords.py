#!/usr/bin/env python3
"""按连续去重后的《说文广义》字头流重排既有物理列。

只更新 chars.json 的 char 字段。顺序固定为页码递增、同页按物理 x 坐标右至左；
以一个用户确认的页/列/字锚点定位来源，且必须顺排到最后有框页。
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


def physical_slots(work_dir: Path, start_page: int, end_page: int):
    """返回物理读取顺序的 (page, column) 槽位及其页面内容。"""
    slots, pages = [], {}
    for page in range(start_page, end_page + 1):
        path = work_dir / ".debug" / f"fatie-{page:04d}" / "chars.json"
        if not path.exists():
            continue
        items = json.loads(path.read_text())
        groups: dict[int, list[dict]] = {}
        for item in items:
            column = item.get("column", item.get("col"))
            if isinstance(column, int):
                groups.setdefault(column, []).append(item)

        def centre(group: list[dict]) -> float:
            return sum((item["bbox"][0] + item["bbox"][2]) / 2 for item in group) / len(group)

        for column, _ in sorted(groups.items(), key=lambda pair: centre(pair[1]), reverse=True):
            slots.append((page, column))
        pages[page] = (path, items)
    return slots, pages


def last_annotated_page(work_dir: Path) -> int:
    pages = [
        int(path.parent.name.removeprefix("fatie-"))
        for path in (work_dir / ".debug").glob("fatie-*/chars.json")
        if path.parent.name.removeprefix("fatie-").isdigit()
    ]
    if not pages:
        raise ValueError("未找到 chars.json")
    return max(pages)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start-page", type=int, required=True)
    parser.add_argument("--start-column", type=int, required=True)
    parser.add_argument("--anchor-char")
    parser.add_argument("--anchor-source-entry", type=int, help="同字头重复时，以原始释文条目号精确定位")
    parser.add_argument(
        "--preserve-tail",
        action="store_true",
        help="来源不足时，已知部分仍顺排；末尾不足列保留当前字并写入审计",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if bool(args.anchor_char) == bool(args.anchor_source_entry):
        raise ValueError("--anchor-char 与 --anchor-source-entry 必须且只能指定一个")
    if args.anchor_char and len(args.anchor_char) != 1:
        raise ValueError("--anchor-char 必须为一个字")

    end_page = last_annotated_page(args.work_dir)
    source_path = args.work_dir / "shidian-headwords-consecutive-deduped.json"
    source = json.loads(source_path.read_text())
    labels = source["headwords"]
    invalid_labels = [item for item in labels if len(str(item.get("char", ""))) != 1]
    if invalid_labels:
        detail = "、".join(
            f"第 {item.get('source_entry')} 条={item.get('char')!r}" for item in invalid_labels[:8]
        )
        raise ValueError(f"去重释文表含多字或空字条目（{detail}）；拒绝顺排。")
    candidates = (
        [i for i, item in enumerate(labels) if item["source_entry"] == args.anchor_source_entry]
        if args.anchor_source_entry
        else [i for i, item in enumerate(labels) if item["char"] == args.anchor_char]
    )
    if len(candidates) != 1:
        value = args.anchor_source_entry if args.anchor_source_entry else args.anchor_char
        raise ValueError(f"锚点 {value!r} 在去重表中出现 {len(candidates)} 次，无法唯一定位")
    source_index = candidates[0]
    anchor_char = labels[source_index]["char"]
    slots, pages = physical_slots(args.work_dir, args.start_page, end_page)
    try:
        anchor_slot = slots.index((args.start_page, args.start_column))
    except ValueError as error:
        raise ValueError("指定的起始页/列不是可用物理列") from error
    # 页面中部也可作为锚点；锚点右侧的列属于前一部，必须原样保留。
    slots = slots[anchor_slot:]

    unresolved = [
        item for item in labels[source_index:source_index + len(slots)]
        if item.get("status") == "unresolved_duplicate_headword"
    ]
    if unresolved:
        detail = "、".join(f"第 {item['source_entry']} 条" for item in unresolved[:8])
        raise ValueError(
            f"去重表含 {len(unresolved)} 条未校勘的连续同字头（{detail}）。"
            "请在 shidian-consecutive-dedup-exceptions.json 写入字头覆写或明确续行；拒绝静默丢字后顺排。"
        )

    available = len(labels) - source_index
    shortfall = max(0, len(slots) - available)
    if shortfall and not args.preserve_tail:
        raise ValueError(
            f"去重释文从第 {source_index + 1} 字“{anchor_char}”起仅余 {available} 字，"
            f"而第 {args.start_page:04d} 页至第 {end_page:04d} 页共有 {len(slots)} 物理列；"
            f"末尾差 {shortfall} 字。需要继续写入已知部分时，请加 --preserve-tail。"
        )

    assignments = []
    for (page, column), source_item in zip(slots, labels[source_index:]):
        assignments.append({
            "page": page,
            "column": column,
            "char": source_item["char"],
            "source_entry": source_item["source_entry"],
            "deduped_index": source_index + len(assignments) + 1,
        })
    tail_preserved = []
    for page, column in slots[len(assignments):]:
        _, items = pages[page]
        old_labels = {
            str(item.get("char", "")).strip()
            for item in items
            if item.get("column", item.get("col")) == column
        }
        old_labels.discard("")
        if len(old_labels) > 1:
            raise ValueError(f"第 {page:04d} 页 col={column} 原有字不一致，拒绝保留尾部")
        char = next(iter(old_labels), "")
        assignments.append({"page": page, "column": column, "char": char, "source_entry": None, "deduped_index": None})
        tail_preserved.append({"page": page, "column": column, "char": char})
    audit = {
        "mode": "consecutive_deduped_headwords",
        "source": str(source_path),
        "anchor": {"page": args.start_page, "column": args.start_column, "char": anchor_char, "source_entry": args.anchor_source_entry},
        "start_deduped_index": source_index + 1,
        "end_page": end_page,
        "slots": len(slots),
        "source_shortfall": shortfall,
        "tail_preserved": tail_preserved,
        "assignments": assignments,
    }
    print(json.dumps({key: value for key, value in audit.items() if key != "assignments"}, ensure_ascii=False))
    if not args.apply:
        return

    for assignment in assignments:
        _, items = pages[assignment["page"]]
        for item in items:
            if item.get("column", item.get("col")) == assignment["column"]:
                item["char"] = assignment["char"]
    for page, column in slots:
        _, items = pages[page]
        values = {str(item.get("char", "")) for item in items if item.get("column", item.get("col")) == column}
        if len(values) != 1 or len(next(iter(values))) != 1:
            raise ValueError(f"第 {page:04d} 页 col={column} 未收敛为唯一单字，拒绝写入")
    by_page: dict[int, list[tuple[float, int, str]]] = {}
    for page, column in slots:
        _, items = pages[page]
        group = [item for item in items if item.get("column", item.get("col")) == column]
        center = sum((item["bbox"][0] + item["bbox"][2]) / 2 for item in group) / len(group)
        by_page.setdefault(page, []).append((center, column, str(group[0]["char"])))
    for page, groups in by_page.items():
        ordered = sorted(groups, reverse=True)
        for (_, right_column, right_char), (_, left_column, left_char) in zip(ordered, ordered[1:]):
            if right_char == left_char:
                raise ValueError(
                    f"第 {page:04d} 页相邻 col={right_column}/col={left_column} 同为 {right_char!r}；"
                    "请将后一个源条目登记为 continuation 后再顺排"
                )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path, items in pages.values():
        backup = path.parent / "backups"
        backup.mkdir(exist_ok=True)
        shutil.copy2(path, backup / f"chars-before-consecutive-deduped-reflow-{stamp}.json")
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n")
    audit_path = args.work_dir / f"consecutive-deduped-reflow-{args.start_page:04d}-{end_page:04d}.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(f"已写入；审计：{audit_path}")


if __name__ == "__main__":
    main()
