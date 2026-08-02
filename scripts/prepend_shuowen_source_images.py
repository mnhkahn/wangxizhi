#!/usr/bin/env python3
"""把识典缺失的卷首扫描图补回本地卷目录，并整体顺延已有页码。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import cv2


SOURCE_URL = "https://www.shidianguji.com/book/HY2666"


def numbered_files(directory: Path, suffix: str) -> dict[int, Path]:
    result: dict[int, Path] = {}
    if not directory.exists():
        return result
    for path in directory.glob(f"fatie-*{suffix}"):
        try:
            result[int(path.stem.removeprefix("fatie-"))] = path
        except ValueError:
            continue
    return result


def check_contiguous(items: dict[int, Path], label: str) -> None:
    if not items:
        return
    expected = set(range(max(items) + 1))
    if set(items) != expected:
        missing = sorted(expected - set(items))
        raise RuntimeError(f"{label} 编号不连续，缺少：{missing[:20]}")


def download(url: str, target: Path) -> None:
    part = target.with_suffix(".part")
    part.unlink(missing_ok=True)
    subprocess.run(
        [
            "curl", "--noproxy", "*", "-fsSL", "--retry", "8",
            "--retry-all-errors", "--connect-timeout", "10", "--max-time", "90",
            "-o", str(part), url,
        ],
        check=True,
    )
    part.rename(target)
    image = cv2.imread(str(target), cv2.IMREAD_UNCHANGED)
    if image is None or image.shape[0] < 1000 or image.shape[1] < 800:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"下载结果不是有效原图：{target}")


def shift_numbered(items: dict[int, Path], offset: int, suffix: str) -> None:
    for index in sorted(items, reverse=True):
        items[index].rename(items[index].with_name(f"fatie-{index + offset:04d}{suffix}"))


def run(work_dir: Path, source_json: Path, expected_start: int) -> None:
    pages = json.loads(source_json.read_text())
    if len(pages) != 40:
        raise RuntimeError(f"补图清单应为 40 张，实际为 {len(pages)}")
    page_numbers = [int(page["pageNum"]) for page in pages]
    if page_numbers != list(range(expected_start, expected_start + 40)):
        raise RuntimeError(f"源页范围不符：{page_numbers[0]}–{page_numbers[-1]}")

    images = numbered_files(work_dir, ".webp")
    check_contiguous(images, f"{work_dir.name} 图片")
    if not images:
        raise RuntimeError(f"目录中没有现有图片：{work_dir}")

    manifest_path = work_dir / "source-manifest.jsonl"
    old_manifest = [json.loads(line) for line in manifest_path.read_text().splitlines() if line.strip()]
    by_page: dict[int, dict] = {}
    for item in old_manifest:
        by_page.setdefault(int(item["source_page_num"]), item)
    old_start = expected_start + 40
    old_end = old_start + len(images) - 1
    expected_old_pages = set(range(old_start, old_end + 1))
    if set(by_page) != expected_old_pages:
        missing = sorted(expected_old_pages - set(by_page))
        extra = sorted(set(by_page) - expected_old_pages)
        raise RuntimeError(f"旧清单页码不符，缺少 {missing[:10]}，多出 {extra[:10]}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stage = work_dir / ".prepend-source-staging"
    stage.mkdir(exist_ok=True)
    operation_complete = False
    try:
        jobs: dict = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            for index, page in enumerate(pages):
                target = stage / f"fatie-{index:04d}.webp"
                cached = cv2.imread(str(target), cv2.IMREAD_UNCHANGED)
                if cached is not None and cached.shape[0] >= 1000 and cached.shape[1] >= 800:
                    continue
                jobs[pool.submit(download, page["picUrl"], target)] = (index, page)
            completed = 40 - len(jobs)
            for future in as_completed(jobs):
                index, page = jobs[future]
                future.result()
                completed += 1
                print(
                    f"{work_dir.name}: 下载 {completed}/40（源页 {page['pageNum']}）",
                    flush=True,
                )

        debug_items = numbered_files(work_dir / ".debug", "")
        words_items = numbered_files(work_dir / "words", ".txt")
        shift_numbered(images, 40, ".webp")
        shift_numbered(debug_items, 40, "")
        shift_numbered(words_items, 40, ".txt")
        for index in range(40):
            (stage / f"fatie-{index:04d}.webp").rename(work_dir / f"fatie-{index:04d}.webp")

        backup = work_dir / f"source-manifest-before-prepend-{stamp}.jsonl"
        shutil.copy2(manifest_path, backup)
        rebuilt: list[dict] = []
        for index, page in enumerate(pages):
            rebuilt.append({
                "file": f"fatie-{index:04d}.webp",
                "source_page_num": int(page["pageNum"]),
                "source_uri": page["uri"],
                "source_url": SOURCE_URL,
            })
        for index, page_num in enumerate(range(old_start, old_end + 1), start=40):
            item = dict(by_page[page_num])
            item["file"] = f"fatie-{index:04d}.webp"
            rebuilt.append(item)
        manifest_path.write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rebuilt)
        )
        operation_complete = True
    finally:
        if operation_complete and stage.exists():
            shutil.rmtree(stage)

    print(
        f"{work_dir.name}: 完成，共 {len(images) + 40} 张，"
        f"源页 {expected_start}–{old_end}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("source_json", type=Path)
    parser.add_argument("expected_start", type=int)
    args = parser.parse_args()
    run(args.work_dir, args.source_json, args.expected_start)


if __name__ == "__main__":
    main()
