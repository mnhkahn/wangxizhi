#!/usr/bin/env python3
"""按《史典古籍》释文顺序为《说文广义》的篆书列填字。

只更新空列的 ``char``，不会改 bbox、column、row 或人工已有的字；每页
写入前都会在 ``backups/`` 留一份原始 chars.json，并输出可复核的对应清单。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from propagate_seal_column_labels import column_groups


HEADWORD_PREFIX = re.compile(r"^([^，。；：、]{1,2})[，。；：、]")
COMMENTARY_PREFIX = re.compile(
    r"^(?:(?:聲|声)[。．]|徐錯曰|徐锴曰|臣鉉等曰|臣鍇曰|按曰|案曰|(?:屬|属)皆(?:从|從)|酒[，,]並省)"
)


def normalize_headword(value: object) -> str:
    """把史典把同一篆字重复识别成的字串还原成单字。"""
    text = str(value or "").strip(" \t\r\n，。；：、")
    if text and len(set(text)) == 1:
        return text[0]
    return text


def usable_entries(path: Path) -> list[dict]:
    """过滤续行，并恢复一条字头下各释文行自己的字头。

    多数卷是一条字头配一条释文；卷十一等页面会把数个字放在同一
    ``lineType=1`` 字头下，后续字写在释文开头（如“觚，……”）。
    旧逻辑会把这些列全写成第一个字，这里按释文前缀还原。
    """
    data = json.loads(path.read_text())
    result: list[dict] = []
    seen_by_line: dict[object, int] = {}
    last_label_by_line: dict[object, str] = {}

    for entry in data["entries"]:
        gloss = str(entry.get("gloss", ""))
        headword = normalize_headword(entry.get("headword", ""))
        is_manual_entry = entry.get("headword_resolution") == "manual_from_page"
        is_continuation = entry.get("headword_resolution") == "continuation"
        # 人工标记的续文绝不能消耗字头序列；它即使是该行的第一条 OCR
        # 记录，也仍然只是上一个字的释文延续。
        if is_continuation:
            continue
        has_component_note = "从" in gloss or "從" in gloss
        # 「芇，相當也…母官切」和「丅，底也。指事胡雅切」都是完整
        # 释文，但比通用长度门槛短，旧逻辑会误删并令后文整体错位。
        # 只为这两条已经原页确认的字头放行，避免放宽全局规则。
        is_complete_definition = (
            (len(gloss) >= 15 or headword in {"芇", "丅"}) and "切" in gloss
        )
        if not is_manual_entry and not has_component_note and not is_complete_definition:
            continue
        # 有些页只识别出了同一篆形的重复串，前后都没有单字字头。只要
        # 重复串能无歧义地归一成一个字符，仍保留该词条；具体无法确认的
        # 个别项可由 --skip-source 配合留空列跳过。
        if len(headword) != 1:
            continue

        line_id = entry.get("headword_line_id")
        occurrence = seen_by_line.get(line_id, 0)
        prefix = HEADWORD_PREFIX.match(gloss)
        # 释文续句常以“也。”收束；它不是新字头，不能消耗一个篆书列。
        has_new_headword_prefix = bool(
            prefix and len(prefix.group(1)) == 1 and prefix.group(1) != "也"
        )
        # 同一字头的长释文会被识典按页拆成数行；没有新单字前缀的后续行
        # 只是续文，不能再次消耗一个篆字列（如菑后的“甾則下有……”）。
        if (
            occurrence
            and (
                is_continuation
                or
                # 同一个 OCR 字头行被拆成数条释文时，后一条即使仍含
                # “从”也只是续文。只有释文明确以另一个单字开头时，
                # 才把它视为共用字头行中的新词条。
                (
                    headword == last_label_by_line.get(line_id)
                    and not has_new_headword_prefix
                )
                or
                COMMENTARY_PREFIX.match(gloss)
                or (
                    not has_new_headword_prefix
                    and not has_component_note
                    and not is_complete_definition
                )
            )
        ):
            continue
        label = headword
        if occurrence:
            # OCR 偶尔把同一字头行中的下一个字认成前一个字；经原页
            # 人工校正后的 headword 应优先于上一条标签。
            if headword != last_label_by_line.get(line_id):
                label = headword
            elif has_new_headword_prefix:
                label = prefix.group(1)
            else:
                label = last_label_by_line.get(line_id, headword)

        cleaned = dict(entry)
        cleaned["headword"] = label
        result.append(cleaned)
        seen_by_line[line_id] = occurrence + 1
        last_label_by_line[line_id] = label

    return result


def stored_column_groups(entries: list[dict]) -> list[list[dict]]:
    """按已确认的 ``column`` 字段分组，并按页面的右至左顺序返回。

    两个相邻版格有时只相距约一个字宽。用于补框的宽松坐标聚类会把它们
    合并，造成两列继承同一个释文；当列号已由人工校正时，应以列号为准。
    """
    groups: dict[int, list[dict]] = {}
    for item in entries:
        column = item.get("column", item.get("col"))
        if not isinstance(column, int):
            continue
        groups.setdefault(column, []).append(item)

    def center(group: list[dict]) -> float:
        return sum((item["bbox"][0] + item["bbox"][2]) / 2 for item in group) / len(group)

    return sorted(groups.values(), key=center, reverse=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start-page", type=int, required=True)
    parser.add_argument("--end-page", type=int, required=True)
    parser.add_argument("--start-source", type=int, required=True, help="清洗后来源的 1 起始条目")
    parser.add_argument("--source", type=Path, help="默认读取字帖目录下的 shidian-glosses.json")
    parser.add_argument(
        "--leave-leading-groups",
        type=int,
        default=0,
        help="卷首无法确认的篆字列留空，且不消耗释文字头",
    )
    parser.add_argument(
        "--leave-group",
        type=int,
        action="append",
        default=[],
        help="指定从起始页算起、0 起始的篆字列留空；可重复使用",
    )
    parser.add_argument(
        "--skip-source",
        type=int,
        action="append",
        default=[],
        help="跳过清洗后来源中的指定条目（1 起始）；可重复使用",
    )
    parser.add_argument("--overwrite", action="store_true", help="重写已有字；用于修正已知来源偏移")
    parser.add_argument(
        "--strict-columns",
        action="store_true",
        help="严格按 chars.json 的 column 字段分列，避免相邻版格被坐标聚类合并",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    source = args.source or args.work_dir / "shidian-glosses.json"
    entries = usable_entries(source)
    offset = args.start_source - 1
    assignments: list[dict] = []
    cursor = offset
    physical_cursor = 0
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    for page in range(args.start_page, args.end_page + 1):
        debug = args.work_dir / ".debug" / f"fatie-{page:04d}"
        chars_path = debug / "chars.json"
        if not chars_path.exists():
            continue
        chars = json.loads(chars_path.read_text())
        groups = (
            stored_column_groups(chars)
            if args.strict_columns and chars
            else column_groups(chars, 180) if chars else []
        )
        changed = False
        for column, group in enumerate(groups):
            leave_groups = set(range(args.leave_leading_groups)) | set(args.leave_group)
            if physical_cursor in leave_groups:
                existing = {str(item.get("char", "")).strip() for item in group} - {""}
                if args.overwrite and existing:
                    for item in group:
                        item["char"] = ""
                    changed = True
                assignments.append({
                    "page": page,
                    "column": column,
                    "char": "",
                    "source_index": None,
                    "headword_line_id": None,
                    "kept_existing": bool(existing) and not args.overwrite,
                    "intentionally_blank": True,
                })
                physical_cursor += 1
                continue
            while cursor + 1 in set(args.skip_source):
                cursor += 1
            if cursor >= len(entries):
                raise RuntimeError("来源释文不足，已停止写入")
            entry = entries[cursor]
            label = str(entry["headword"])
            existing = {str(item.get("char", "")).strip() for item in group} - {""}
            if not existing or args.overwrite:
                for item in group:
                    item["char"] = label
                changed = True
            assignments.append({
                "page": page,
                "column": column,
                "char": label,
                "source_index": cursor + 1,
                "headword_line_id": entry.get("headword_line_id"),
                "kept_existing": bool(existing),
            })
            cursor += 1
            physical_cursor += 1
        if args.apply and changed:
            backups = debug / "backups"
            backups.mkdir(exist_ok=True)
            shutil.copy2(chars_path, backups / f"chars-before-shidian-labels-{stamp}.json")
            chars_path.write_text(json.dumps(chars, ensure_ascii=False, indent=2) + "\n")

    audit = {
        "source": str(source),
        "start_source": args.start_source,
        "next_source": cursor + 1,
        "assignments": assignments,
    }
    audit_path = args.work_dir / f"shidian-labels-{args.start_page:04d}-{args.end_page:04d}.json"
    if args.apply:
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(f"列数：{len(assignments)}；来源 {args.start_source}..{cursor}；审计：{audit_path}")


if __name__ == "__main__":
    main()
