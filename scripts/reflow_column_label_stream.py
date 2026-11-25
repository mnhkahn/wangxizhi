#!/usr/bin/env python3
"""安全地顺排《说文广义》的列字流。

只更新 char 字段。读取顺序永远是：页码递增、同页按实际 x 坐标右至左。
默认预览；--apply 前在内存完成全部移动、校验同列一致性，并生成备份和审计。
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


def read_stream(work_dir: Path, start: int, end: int):
    stream, pages = [], {}
    for page in range(start, end + 1):
        path = work_dir / ".debug" / f"fatie-{page:04d}" / "chars.json"
        if not path.exists():
            continue
        items = json.loads(path.read_text())
        groups = {}
        for item in items:
            col = item.get("column", item.get("col"))
            if isinstance(col, int):
                groups.setdefault(col, []).append(item)
        def center(group):
            return sum((x["bbox"][0] + x["bbox"][2]) / 2 for x in group) / len(group)
        for col, group in sorted(groups.items(), key=lambda pair: center(pair[1]), reverse=True):
            values = {str(x.get("char", "")).strip() for x in group}
            values.discard("")
            if len(values) > 1:
                raise ValueError(f"{page:04d}/col={col} 同列字不一致：{sorted(values)}")
            stream.append({"page": page, "column": col, "char": next(iter(values), "")})
        pages[page] = [path, items]
    return stream, pages


def duplicates(stream):
    seen, result = {}, []
    for index, slot in enumerate(stream):
        char = slot["char"]
        if not char:
            continue
        page_seen = seen.setdefault(slot["page"], set())
        if char in page_seen:
            result.append({**slot, "slot_index": index})
        else:
            page_seen.add(char)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start-page", type=int, required=True)
    parser.add_argument("--end-page", type=int, required=True)
    parser.add_argument("--page", type=int, help="目标页（insert/remove 必填）")
    parser.add_argument("--column", type=int, help="目标列（insert/remove 必填）")
    parser.add_argument("--insert", help="插入的单字；后续全部后移")
    parser.add_argument("--remove", action="store_true", help="删除目标槽位字；后续全部前移")
    parser.add_argument("--remove-label", help="删除范围内所有等于此单字的标签；后续全部前移")
    parser.add_argument("--tail-label", help="删除时补回末尾字，适用于撤销一次已暂存溢出的插入")
    parser.add_argument("--dedupe-page-duplicates", action="store_true",
                        help="删除同页中较后的重复字；后续全部跨页前移")
    parser.add_argument("--allow-page-duplicates", action="store_true",
                        help="允许同页出现相同字；人工确认的重复字不视为写入错误")
    parser.add_argument("--allow-tail-blanks", action="store_true",
                        help="明确允许删除/去重后在范围末尾留下空槽")
    parser.add_argument("--stash-overflow", action="store_true",
                        help="插入时将范围末尾被挤出的字暂存，默认拒绝写入")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    actions = int(args.insert is not None) + int(args.remove) + int(args.remove_label is not None) + int(args.dedupe_page_duplicates)
    if actions != 1:
        raise ValueError("--insert、--remove、--remove-label、--dedupe-page-duplicates 必须四选一")
    if args.insert is not None and len(args.insert) != 1:
        raise ValueError("--insert 必须为单字")
    if args.remove_label is not None and len(args.remove_label) != 1:
        raise ValueError("--remove-label 必须为单字")
    if args.tail_label is not None and (not args.remove or len(args.tail_label) != 1):
        raise ValueError("--tail-label 只能与 --remove 一起使用，且必须为单字")
    if not (args.dedupe_page_duplicates or args.remove_label is not None) and (args.page is None or args.column is None):
        raise ValueError("insert/remove 必须指定 --page 和 --column")

    stream, pages = read_stream(args.work_dir, args.start_page, args.end_page)
    original = [slot["char"] for slot in stream]
    removed = []
    overflow = ""
    if args.remove_label is not None:
        removed = [{**slot, "slot_index": index} for index, slot in enumerate(stream) if slot["char"] == args.remove_label]
        if not removed:
            raise ValueError(f"范围内没有标签「{args.remove_label}」")
        cut = {item["slot_index"] for item in removed}
        labels = [char for index, char in enumerate(original) if index not in cut]
        labels += [""] * len(cut)
        operation = "remove_label"
    elif args.dedupe_page_duplicates:
        # 前移后，下一页可能又带入一个同页重复字；因此必须反复扫描，
        # 直到整条列流稳定，而不是只处理第一批重复。
        labels = original
        while True:
            candidate = [{**slot, "char": label} for slot, label in zip(stream, labels)]
            repeated = duplicates(candidate)
            if not repeated:
                break
            removed.extend(repeated)
            cut = {item["slot_index"] for item in repeated}
            labels = [char for index, char in enumerate(labels) if index not in cut]
            labels += [""] * len(cut)
        operation = "dedupe_page_duplicates"
    else:
        try:
            index = next(
                i for i, slot in enumerate(stream)
                if (slot["page"], slot["column"]) == (args.page, args.column)
            )
        except StopIteration as error:
            raise ValueError("目标页/列不存在") from error
        if args.remove:
            removed = [{**stream[index], "slot_index": index}]
            labels = original[:index] + original[index + 1:] + [args.tail_label or ""]
            operation = "remove"
        else:
            overflow = original[-1]
            if overflow and not args.stash_overflow:
                raise ValueError(
                    f"插入会使末尾字「{overflow}」溢出，拒绝写入；"
                    "请加 --stash-overflow 保存待承接字"
                )
            labels = original[:index] + [args.insert] + original[index:-1]
            operation = "insert"

    candidate = [{**slot, "char": label} for slot, label in zip(stream, labels)]
    remaining = duplicates(candidate)
    if remaining and not args.allow_page_duplicates:
        raise ValueError("重排后仍有重复，拒绝写入：" + json.dumps(remaining[:10], ensure_ascii=False))
    audit = {
        "operation": operation,
        "range": [args.start_page, args.end_page],
        "slots": len(stream),
        "removed_or_overflow": removed,
        "overflow": overflow or None,
        "tail_blanks": sum(1 for char in labels if not char),
        "page_duplicates": remaining,
    }
    original_tail_blanks = sum(1 for char in original if not char)
    if (
        audit["tail_blanks"] > original_tail_blanks
        and args.apply
        and not args.allow_tail_blanks
    ):
        raise ValueError(
            f"重排会新增 {audit['tail_blanks'] - original_tail_blanks} 个末尾空槽，拒绝写入。"
            "请扩大 --end-page 让后续字承接，或人工确认后加 --allow-tail-blanks"
        )
    print(json.dumps(audit, ensure_ascii=False))
    if not args.apply:
        return

    for slot, label in zip(stream, labels):
        _, items = pages[slot["page"]]
        for item in items:
            if item.get("column", item.get("col")) == slot["column"]:
                item["char"] = label
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if overflow:
        stash_path = args.work_dir / "pending-overflow-labels.json"
        stash = json.loads(stash_path.read_text()) if stash_path.exists() else []
        stash.insert(0, {
            "char": overflow,
            "operation": operation,
            "start_page": args.page,
            "start_column": args.column,
            "end_page": args.end_page,
            "stashed_at": datetime.now().isoformat(timespec="seconds"),
        })
        stash_path.write_text(json.dumps(stash, ensure_ascii=False, indent=2) + chr(10))
    for path, items in pages.values():
        backup = path.parent / "backups"
        backup.mkdir(exist_ok=True)
        shutil.copy2(path, backup / f"chars-before-stream-reflow-{stamp}.json")
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + chr(10))
    audit_path = args.work_dir / f"column-stream-reflow-{args.start_page:04d}-{args.end_page:04d}.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + chr(10))
    print(f"已写入；审计：{audit_path}")


if __name__ == "__main__":
    main()
