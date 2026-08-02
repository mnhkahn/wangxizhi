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


def extract_lines(source: str) -> list[tuple[int, int, str]]:
    """读取页面内嵌的识典逐行文本。"""
    return [
        (int(match["id"]), int(match["type"]), html.unescape(match["content"]))
        for match in LINE_PATTERN.finditer(source)
    ]


def extract_entries(lines: list[tuple[int, int, str]], volume_title: str) -> list[dict[str, object]]:
    """由字头行与释文行组成可追溯的条目列表。"""
    starts = [index for index, (_, _, content) in enumerate(lines) if content == volume_title]
    if not starts:
        raise ValueError(f"未找到正文卷名 {volume_title!r}")

    entries: list[dict[str, object]] = []
    headword = ""
    headword_line_id: int | None = None
    for line_id, line_type, content in lines[starts[0] :]:
        if line_type == 1 and content:
            headword = content
            headword_line_id = line_id
        elif line_type == 2 and content and headword:
            entries.append(
                {
                    "headword": headword,
                    "gloss": content,
                    "headword_line_id": headword_line_id,
                    "gloss_line_id": line_id,
                }
            )
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("html", type=Path, help="识典章节下载的 HTML")
    parser.add_argument("--volume-title", default="說文廣義卷之五")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    lines = extract_lines(args.html.read_text(encoding="utf-8"))
    entries = extract_entries(lines, args.volume_title)
    args.output.write_text(
        json.dumps(
            {
                "source": "https://www.shidianguji.com/book/HY2666/chapter/1kw4juo9tsfty",
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
