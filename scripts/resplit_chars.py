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
from ocr.preprocess import detect_content_region


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

    # 检测并裁剪黑色主体区域（去掉白色边框）
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    content_bbox = detect_content_region(gray)
    offset_x, offset_y = 0, 0
    if content_bbox is not None:
        cx1, cy1, cx2, cy2 = content_bbox
        image = image[cy1:cy2+1, cx1:cx2+1]
        offset_x, offset_y = cx1, cy1

    # 按 column 分组
    col_groups = defaultdict(list)
    for c in chars:
        col_groups[c.get("column", 0)].append(c)

    # 优先从 result.json 读取列 bbox（更可靠，不会被 resplit 污染）
    result_path = chars_path.parent / "result.json"
    col_bboxes_from_result = {}
    if result_path.exists():
        try:
            with open(result_path, "r", encoding="utf-8") as f:
                result_data = json.load(f)
            parsed_results = result_data.get("parsed_results", [])
            if parsed_results:
                # 过滤释文列（窄列）
                widths = [c["bbox"][2] - c["bbox"][0] for c in parsed_results]
                max_width = max(widths) if widths else 0
                threshold = max(max_width * 0.5, 50)
                valid_cols = [c for c in parsed_results if c["bbox"][2] - c["bbox"][0] >= threshold]
                # 按 x_max 从大到小排序（从右到左），与 chars.json 的 column 编号对应
                valid_cols.sort(key=lambda c: -c["bbox"][2])
                if len(valid_cols) == len(col_groups):
                    for col_idx, col_data in enumerate(valid_cols):
                        col_bboxes_from_result[col_idx] = col_data["bbox"]
        except Exception:
            pass

    updated_count = 0
    skipped_cols = 0

    for col_idx, items in col_groups.items():
        items.sort(key=lambda x: x.get("row", 0))
        text = "".join(c.get("char", "") for c in items)
        if not text:
            continue

        # 获取列 bbox
        if col_idx in col_bboxes_from_result:
            # 使用 result.json 的列 bbox（原图坐标）
            col_bbox = list(col_bboxes_from_result[col_idx])
            # 映射到裁剪图坐标
            if content_bbox is not None:
                col_bbox = [
                    col_bbox[0] - offset_x,
                    col_bbox[1] - offset_y,
                    col_bbox[2] - offset_x,
                    col_bbox[3] - offset_y,
                ]
        else:
            # 回退：从 chars.json 的字 bbox 计算列 bbox（已可能被污染）
            bboxes = [c.get("bbox", [0, 0, 0, 0]) for c in items]
            try:
                x1 = min(b[0] for b in bboxes) - offset_x
                y1 = min(b[1] for b in bboxes) - offset_y
                x2 = max(b[2] for b in bboxes) - offset_x
                y2 = max(b[3] for b in bboxes) - offset_y
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
            b = char_bboxes[j]
            # 收紧 bbox，去掉白边（在裁剪图坐标下）
            from ocr.preprocess import tighten_char_bbox
            b = tighten_char_bbox(image, b, pad=3)
            # 把 bbox 映射回原图坐标
            item["bbox"] = [
                float(b[0] + offset_x),
                float(b[1] + offset_y),
                float(b[2] + offset_x),
                float(b[3] + offset_y),
            ]
            updated_count += 1

    # 保存
    with open(chars_path, "w", encoding="utf-8") as f:
        json.dump(chars, f, ensure_ascii=False, indent=2)

    msg = f"已更新 {updated_count} 个字的 bbox"
    if content_bbox is not None:
        msg += f"，已裁剪白色边框"
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
