#!/usr/bin/env python3
"""
快速验证拆字修复效果
用法：python test_split_fix.py <字帖目录> <图片名，如 fatie-000>
"""
import sys
import json
import cv2
import numpy as np
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from ocr.char_splitter import CharSplitter, SplitMethod


def test_split(work_dir: str, stem: str):
    work_path = Path(work_dir)
    img_path = None
    for ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
        cand = work_path / f"{stem}{ext}"
        if cand.exists():
            img_path = cand
            break
    if img_path is None:
        print(f"找不到图片: {work_dir}/{stem}.*")
        return

    chars_path = work_path / ".debug" / stem / "chars.json"
    if not chars_path.exists():
        print(f"chars.json 不存在: {chars_path}")
        return

    with open(chars_path, "r", encoding="utf-8") as f:
        chars = json.load(f)

    image = cv2.imread(str(img_path))
    if image is None:
        print("无法加载图片")
        return

    splitter = CharSplitter(method=SplitMethod.HYBRID, min_char_height=20)

    col_groups = defaultdict(list)
    for c in chars:
        col_groups[c.get("column", 0)].append(c)

    print(f"\n📄 {img_path}")
    print("=" * 60)

    for col_idx in sorted(col_groups.keys()):
        items = col_groups[col_idx]
        items.sort(key=lambda x: x.get("row", 0))
        text = "".join(c.get("char", "") for c in items)
        if not text:
            continue

        bboxes = [c.get("bbox", [0, 0, 0, 0]) for c in items]
        x1 = min(b[0] for b in bboxes)
        y1 = min(b[1] for b in bboxes)
        x2 = max(b[2] for b in bboxes)
        y2 = max(b[3] for b in bboxes)
        col_bbox = [float(x1), float(y1), float(x2), float(y2)]

        char_bboxes, method = splitter.split_column(image, col_bbox, text, debug=False)

        heights = [b[3] - b[1] for b in char_bboxes]
        std = np.std(heights)
        print(f"\n列 {col_idx}: '{text}'  [{method}]")
        print(f"  字高: {[int(h) for h in heights]}")
        print(f"  标准差: {std:.1f}")

        if std < 1.0:
            print(f"  ⚠️  警告: 这列几乎是均匀分割，可能该列图像对比度不足")
        else:
            print(f"  ✅ 已根据图像内容非均匀分割")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        test_split(sys.argv[1], sys.argv[2])
    else:
        # 默认测试圣教序第一张
        test_split("王羲之-行书-圣教序", "fatie-000")
