#!/usr/bin/env python3
"""
批量重新拆字：只更新 bbox，不修改字/id/author/font/work/visible/column/row。
用法：
    python scripts/resplit_chars.py 王羲之-行书-千字文 --start 009
"""

import sys
import json
import argparse
from pathlib import Path
from collections import defaultdict

# 确保能 import 到 ocr 模块
sys.path.insert(0, str(Path(__file__).parent.parent))

import cv2
from ocr.char_splitter import CharSplitter, SplitMethod


def resplit_image(image_path: Path, splitter: CharSplitter) -> tuple:
    """对单张图片重新拆字，返回 (ok, message)。"""
    chars_path = image_path.parent / ".debug" / image_path.stem / "chars.json"

    if not chars_path.exists():
        return False, "chars.json 不存在"

    with open(chars_path, "r", encoding="utf-8") as f:
        chars = json.load(f)

    if not isinstance(chars, list) or not chars:
        return False, "chars.json 为空"

    image = cv2.imread(str(image_path))
    if image is None:
        return False, "无法加载图片"

    # 按 column 分组
    col_groups = defaultdict(list)
    for c in chars:
        col_groups[c.get("column", 0)].append(c)

    updated_count = 0
    skipped_cols = 0

    for col_idx, items in col_groups.items():
        items.sort(key=lambda x: x.get("row", 0))
        text = "".join(c.get("char", "") for c in items)
        if not text:
            continue

        # 计算列 bbox（所有字 bbox 的并集）
        bboxes = [c.get("bbox", [0, 0, 0, 0]) for c in items]
        try:
            x1 = min(b[0] for b in bboxes)
            y1 = min(b[1] for b in bboxes)
            x2 = max(b[2] for b in bboxes)
            y2 = max(b[3] for b in bboxes)
        except Exception:
            skipped_cols += 1
            continue

        col_bbox = [float(x1), float(y1), float(x2), float(y2)]

        try:
            char_bboxes, method = splitter.split_column(
                image, col_bbox, text, debug=False
            )
        except Exception as e:
            skipped_cols += 1
            continue

        if len(char_bboxes) != len(items):
            skipped_cols += 1
            continue

        for j, item in enumerate(items):
            item["bbox"] = char_bboxes[j]
            updated_count += 1

    # 保存
    with open(chars_path, "w", encoding="utf-8") as f:
        json.dump(chars, f, ensure_ascii=False, indent=2)

    msg = f"已更新 {updated_count} 个字的 bbox"
    if skipped_cols:
        msg += f"，跳过 {skipped_cols} 列"
    return True, msg


def main():
    parser = argparse.ArgumentParser(description="批量重新拆字（只更新 bbox）")
    parser.add_argument("work_dir", help="字帖目录路径")
    parser.add_argument("--start", default="", help="起始编号，如 009")
    args = parser.parse_args()

    work_dir = Path(args.work_dir)
    if not work_dir.exists():
        print(f"目录不存在: {work_dir}")
        sys.exit(1)

    # 收集图片
    images = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        images.extend(work_dir.glob(ext))
    images = sorted(images, key=lambda p: p.name)

    # 过滤起始编号
    if args.start:
        start_name = f"fatie-{args.start}"
        images = [p for p in images if p.stem >= start_name]

    if not images:
        print("未找到符合条件的图片")
        sys.exit(1)

    splitter = CharSplitter(method=SplitMethod.HYBRID, min_char_height=20)

    total = len(images)
    ok_count = 0
    fail_count = 0

    for i, img_path in enumerate(images, start=1):
        ok, msg = resplit_image(img_path, splitter)
        status = "OK" if ok else "FAIL"
        print(f"[{i}/{total}] {status}: {img_path.name} — {msg}")
        if ok:
            ok_count += 1
        else:
            fail_count += 1

    print(f"\n完成：成功 {ok_count}，失败 {fail_count}，共 {total}")


if __name__ == "__main__":
    main()
