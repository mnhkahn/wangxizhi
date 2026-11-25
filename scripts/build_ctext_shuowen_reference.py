#!/usr/bin/env python3
"""从 CText 的《说文解字》部首正文生成可核验的字头序列。

这不是 OCR：每个部首页都以“字头：释文”列出完整条目。脚本只抓取当前
《说文广义》卷十实际涉及的 18 个部首，并把原始网页缓存到工作目录，后续
可离线复查。默认不联网；仅 ``--fetch`` 时请求 CText。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.request
from pathlib import Path


BASE = "https://ctext.org/"
PARTS = [
    ("哭", "shuo-wen-jie-zi/ku-bu/zh"),
    ("谷", "shuo-wen-jie-zi/gu-bu3/zh"),
    ("卜", "shuo-wen-jie-zi/bu-bu1/zh"),
    ("攴", "shuo-wen-jie-zi/pu-bu1/zh"),
    ("木", "shuo-wen-jie-zi/mu-bu1/zh"),
    ("禿", "shuo-wen-jie-zi/tu-bu/zh"),
    ("彔", "shuo-wen-jie-zi/lu-bu/zh"),
    ("鹿", "shuo-wen-jie-zi/lu-bu1/zh"),
    ("畗", "shuo-wen-jie-zi/da-bu/zh"),
    ("目", "shuo-wen-jie-zi/mu-bu/zh"),
    ("尗", "shuo-wen-jie-zi/shu-bu3/zh"),
    ("六", "shuo-wen-jie-zi/liu-bu/zh"),
    ("臼", "shuo-wen-jie-zi/jiu-bu2/zh"),
    ("菐", "shuo-wen-jie-zi/pu-bu/zh"),
    ("束", "shuo-wen-jie-zi/shu-bu1/zh"),
    ("蓐", "shuo-wen-jie-zi/ru-bu/zh"),
    ("足", "shuo-wen-jie-zi/zu-bu/zh"),
    ("玉", "shuo-wen-jie-zi/yu-bu/zh"),
]


def plain(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", "", html.unescape(value))


def parse_entries(page: str, part: str) -> list[dict[str, str]]:
    """取正文表格的“字头：释文”，忽略页面导航和注释按钮。"""
    entries: list[dict[str, str]] = []
    for row in re.findall(r'<tr id="n\d+">(.*?)</tr>', page, re.S):
        match = re.search(
            r'<div id="comm\d+"></div>(.*?)<p class="ctext">', row, re.S
        )
        if not match:
            continue
        text = plain(match.group(1))
        if "：" not in text:
            continue
        headword, gloss = text.split("：", 1)
        # 前一个 td 的“某部”不会落入这里；仍用强校验避免把正文说明误收。
        if len(headword) != 1 or not gloss:
            raise ValueError(f"{part}部出现非单字字头：{headword!r}")
        entries.append({"headword": headword, "gloss": gloss, "part": part})
    if not entries:
        raise ValueError(f"{part}部未解析到正文条目")
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--fetch", action="store_true", help="下载一次并写入 ctext-cache/")
    parser.add_argument("--sleep", type=float, default=1.0, help="每页网络请求间隔秒数")
    parser.add_argument("--limit", type=int, help="只处理前 N 个部首（供中断后的离线校验使用）")
    args = parser.parse_args()

    cache = args.work_dir / "ctext-shuowen-cache"
    cache.mkdir(exist_ok=True)
    all_entries: list[dict[str, str]] = []
    selected_parts = PARTS[:args.limit] if args.limit else PARTS
    for number, (part, relative_url) in enumerate(selected_parts):
        path = cache / f"{number:02d}-{part}.html"
        # 支持网络中断后继续：已成功缓存的部首绝不重复请求。
        if args.fetch and not path.exists():
            request = urllib.request.Request(
                BASE + relative_url,
                headers={"User-Agent": "wangxizhi-shuowen-audit/1.0 (one-time reference cache)"},
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read().decode("utf-8")
            path.write_text(payload)
            time.sleep(args.sleep)
        if not path.exists():
            raise FileNotFoundError(f"缺少缓存：{path}；首次请使用 --fetch")
        all_entries.extend(parse_entries(path.read_text(), part))

    output = {
        "source": "Chinese Text Project, Shuowen Jiezi component pages",
        "source_base": BASE,
        "parts": [{"part": p, "url": BASE + u} for p, u in selected_parts],
        "entry_count": len(all_entries),
        "entries": all_entries,
    }
    destination = args.work_dir / "ctext-shuowen-reference.json"
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"entries": len(all_entries), "output": str(destination)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
