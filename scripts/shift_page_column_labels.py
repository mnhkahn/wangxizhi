#!/usr/bin/env python3
"""在页序/列序中插入一个释文，只移动 ``char`` 字段。

默认不允许丢弃末尾释文。若整个可写范围已满，调用会在写入前失败；
可用 ``--stash-overflow`` 把溢出字写入卷目录的待承接清单；
只有明确传入 ``--discard-overflow`` 才会丢弃溢出的字。
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start-page", type=int, required=True)
    parser.add_argument("--column", type=int, required=True)
    parser.add_argument("--label")
    parser.add_argument("--remove", action="store_true", help="删除起始槽位的字，并将后续字前移")
    parser.add_argument(
        "--discard-overflow",
        action="store_true",
        help="明确允许丢弃末尾溢出的非空释文（默认禁止）",
    )
    parser.add_argument(
        "--stash-overflow",
        action="store_true",
        help="将末尾溢出的非空释文保存到 pending-overflow-labels.json",
    )
    parser.add_argument("--end-page", type=int, required=True)
    args = parser.parse_args()
    if args.remove == (args.label is not None):
        raise ValueError("--label 与 --remove 必须二选一")
    if args.discard_overflow and args.stash_overflow:
        raise ValueError("--discard-overflow 与 --stash-overflow 不能同时使用")

    pages: list[tuple[int, Path, list[dict], list[int]]] = []
    for page in range(args.start_page, args.end_page + 1):
        path = args.work_dir / ".debug" / f"fatie-{page:04d}" / "chars.json"
        if not path.exists():
            continue
        items = json.loads(path.read_text())
        columns = sorted({int(item["column"]) for item in items}, reverse=True)
        if columns:
            pages.append((page, path, items, columns))

    slots = [(page, column) for page, _, _, columns in pages for column in columns]
    try:
        start = slots.index((args.start_page, args.column))
    except ValueError as error:
        raise ValueError("起始页/列没有可写入框") from error

    page_by_number = {page: (path, items) for page, path, items, _ in pages}
    old_labels = [
        next(
            str(item.get("char", ""))
            for item in page_by_number[page][1]
            if int(item["column"]) == column
        )
        for page, column in slots
    ]
    if args.remove:
        new_labels = old_labels[:start] + old_labels[start + 1:] + [""]
        overflow = old_labels[start]
    else:
        new_labels = old_labels[:start] + [args.label] + old_labels[start:-1]
        overflow = old_labels[-1]

    if overflow and not (args.discard_overflow or args.stash_overflow):
        raise ValueError(
            f"操作会丢弃末尾释文「{overflow}」，已取消写入。"
            "请先补足承接字框、传入 --stash-overflow 保存待承接字，"
            "或在人工确认后显式传入 --discard-overflow。"
        )

    if overflow and args.stash_overflow:
        stash_path = args.work_dir / "pending-overflow-labels.json"
        stash = json.loads(stash_path.read_text()) if stash_path.exists() else []
        # 当前正文流的末字先溢出，原先已暂存的字仍排在它之后；
        # 因此必须前插，未来补出新字框时才能按正确顺序接回。
        stash.insert(0, {
            "char": overflow,
            "operation": "remove" if args.remove else "insert",
            "start_page": args.start_page,
            "start_column": args.column,
            "end_page": args.end_page,
            "stashed_at": datetime.now().isoformat(timespec="seconds"),
        })
        stash_path.write_text(json.dumps(stash, ensure_ascii=False, indent=2) + "\n")

    changed: dict[Path, list[dict]] = {}
    for (page, column), label in zip(slots[start:], new_labels[start:]):
        path, items = page_by_number[page]
        for item in items:
            if int(item["column"]) == column:
                item["char"] = label
        changed[path] = items

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path, items in changed.items():
        backup = path.parent / "backups"
        backup.mkdir(exist_ok=True)
        shutil.copy2(path, backup / f"chars-before-column-shift-{stamp}.json")
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n")
    print(f"更新 {len(changed)} 页；末尾溢出：{overflow or '（空）'}")


if __name__ == "__main__":
    main()
