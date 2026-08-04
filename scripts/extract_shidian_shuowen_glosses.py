#!/usr/bin/env python3
"""从识典古籍章节 HTML 提取《说文广义》的标准字及释文。

识典页面内嵌了逐行整理文本。正文每一条通常由「篆字／正字」行
（lineType=1）和紧随其后的释文行（lineType=2）组成；目录以
“卷名目录”标记，而正文以精确卷名标记，因此从精确卷名处开始读取。

本脚本只写出来源清单，不修改任何 chars.json。
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path


LINE_PATTERN = re.compile(
    r'\\"lineId\\":\\"(?P<id>\d+)\\".*?'
    r'\\"lineType\\":(?P<type>\d+),'
    r'\\"content\\":\\"(?P<content>.*?)\\"'
)
HEADWORD_PREFIX = re.compile(r"^([^，。；：、]{1})[，。；：、]")


def extract_lines(source: str) -> list[tuple[int, int, str]]:
    """读取页面内嵌的识典逐行文本。"""
    return [
        (int(match["id"]), int(match["type"]), html.unescape(match["content"]))
        for match in LINE_PATTERN.finditer(source)
    ]


def extract_entries(lines: list[tuple[int, int, str]], volume_title: str) -> list[dict[str, object]]:
    """由字头行与释文行组成可追溯的条目列表。

    识典有时把版面的篆形重复串识别为字头，并把真正的单字字头放在
    释文之后。此时优先使用释文前的单字；若前面是重复串，则使用到
    下一条释文之前出现的首个单字，避免把“𠔼𠔼（同的释文）同”误作
    𠔼，也能保留跨页续行。
    """
    starts = [index for index, (_, _, content) in enumerate(lines) if content == volume_title]
    if not starts:
        raise ValueError(f"未找到正文卷名 {volume_title!r}")

    body = lines[starts[0] :]
    entries: list[dict[str, object]] = []
    previous_headword = ""
    previous_headword_line_id: int | None = None

    def clean_headword(content: str) -> str:
        return content.strip(" \t\r\n，。；：、")

    for index, (line_id, line_type, content) in enumerate(body):
        if line_type == 1 and content:
            previous_headword = content
            previous_headword_line_id = line_id
            continue
        if line_type != 2 or not content or not previous_headword:
            continue

        raw_headword = clean_headword(previous_headword)
        resolved_headword = raw_headword
        resolved_line_id = previous_headword_line_id
        headword_resolution = "single_before" if len(raw_headword) == 1 else "unresolved"
        if len(raw_headword) != 1:
            prefix = HEADWORD_PREFIX.match(content)
            if prefix:
                resolved_headword = prefix.group(1)
                headword_resolution = "gloss_prefix"
            else:
                candidate: tuple[int, str] | None = None
                saw_type1_after_candidate = False
                for next_line_id, next_line_type, next_content in body[index + 1 :]:
                    is_next_definition = (
                        next_line_type == 2
                        and next_content
                        and ("从" in next_content or "從" in next_content)
                    )
                    if is_next_definition:
                        break
                    if next_line_type != 1 or not next_content:
                        continue
                    next_headword = clean_headword(next_content)
                    if candidate is None and len(next_headword) == 1:
                        candidate = (next_line_id, next_headword)
                    elif candidate is not None:
                        saw_type1_after_candidate = True
                if candidate is not None and saw_type1_after_candidate:
                    resolved_line_id, resolved_headword = candidate
                    headword_resolution = "single_after"

        entries.append(
            {
                "headword": resolved_headword,
                "ocr_headword": previous_headword,
                "headword_resolution": headword_resolution,
                "gloss": content,
                "headword_line_id": resolved_line_id,
                "gloss_line_id": line_id,
            }
        )
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("html", type=Path, help="识典章节下载的 HTML")
    parser.add_argument("--volume-title", default="說文廣義卷之五")
    parser.add_argument("--source-url", help="写入结果的识典章节来源 URL")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    lines = extract_lines(args.html.read_text(encoding="utf-8"))
    entries = extract_entries(lines, args.volume_title)
    args.output.write_text(
        json.dumps(
            {
                "source": args.source_url or str(args.html),
                "volume": args.volume_title,
                "entries": entries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"已提取 {len(entries)} 条：{args.output}")


if __name__ == "__main__":
    main()
