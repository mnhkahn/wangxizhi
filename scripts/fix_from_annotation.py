#!/usr/bin/env python3
"""
从 result.json 的释文列提取标准文字，按列分组后修正主文列。
避免跨释文列串行。
"""

import json
import uuid
import sys
from pathlib import Path
from collections import defaultdict
from difflib import SequenceMatcher

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.batch_ocr_and_fix import fix_column


def split_text(text, n_groups):
    """将 text 均匀分成 n_groups 组。"""
    if n_groups <= 0:
        return []
    total = len(text)
    base = total // n_groups
    rem = total % n_groups
    groups = []
    pos = 0
    for i in range(n_groups):
        size = base + (1 if i < rem else 0)
        groups.append(text[pos:pos + size])
        pos += size
    return groups


def fix_page_from_annotation(result_path: Path, chars_path: Path, img_path: Path):
    with open(result_path, 'r', encoding='utf-8') as f:
        result_data = json.load(f)

    parsed_results = result_data.get('parsed_results', [])
    if not parsed_results:
        return None

    col_widths = {}
    for i, p in enumerate(parsed_results):
        bbox = p['bbox']
        avg_w = bbox[2] - bbox[0]
        col_widths[i] = avg_w

    if not col_widths:
        return None

    max_w = max(col_widths.values())
    threshold = max(max_w * 0.5, 50)

    # 释文列（窄列），按 x 从大到小排序
    anno_cols = []
    for col_idx, avg_w in col_widths.items():
        if avg_w < threshold:
            p = parsed_results[col_idx]
            text = p['text'].replace(' ', '').replace('\n', '').replace('\t', '')
            # 过滤掉纯数字的列（页码）
            if text.isdigit():
                continue
            anno_cols.append((col_idx, text, avg_w))
    anno_cols.sort(key=lambda x: -parsed_results[x[0]]['bbox'][0])  # 从右到左

    if not anno_cols:
        return None

    # 读取 chars.json
    with open(chars_path, 'r', encoding='utf-8') as f:
        chars = json.load(f)

    chars_by_col = defaultdict(list)
    for c in chars:
        chars_by_col[c['column']].append(c)

    col_info = []
    for col_key, items in chars_by_col.items():
        avg_x = sum(c['bbox'][0] + c['bbox'][2] for c in items) / (2 * len(items))
        col_info.append((avg_x, col_key, items))
    col_info.sort(reverse=True)  # 从右到左

    n_main = len(col_info)
    total_anno = sum(len(t) for _, t, _ in anno_cols)

    if n_main == 0 or total_anno == 0:
        return None

    # 按字数比例分配每组释文的组数
    group_counts = []
    for _, text, _ in anno_cols:
        g = round(len(text) / total_anno * n_main)
        group_counts.append(max(1, g))

    # 调整使总和等于 n_main
    while sum(group_counts) > n_main:
        # 减少最大比例的一列
        ratios = [len(text) / total_anno * n_main for _, text, _ in anno_cols]
        idx = max(range(len(ratios)), key=lambda i: ratios[i] - group_counts[i])
        if group_counts[idx] > 1:
            group_counts[idx] -= 1
    while sum(group_counts) < n_main:
        ratios = [len(text) / total_anno * n_main for _, text, _ in anno_cols]
        idx = min(range(len(ratios)), key=lambda i: ratios[i] - group_counts[i])
        group_counts[idx] += 1

    # 按列分组
    all_groups = []
    for (_, text, _), gcount in zip(anno_cols, group_counts):
        groups = split_text(text, gcount)
        all_groups.extend(groups)

    # 从 parsed_results 中提取主文列 bbox，按 x 从大到小排序
    parsed_results = result_data.get('parsed_results', [])
    main_col_bboxes = []
    if parsed_results:
        parsed_widths = []
        for p in parsed_results:
            bbox = p['bbox']
            w = bbox[2] - bbox[0]
            parsed_widths.append(w)
        if parsed_widths:
            max_pw = max(parsed_widths)
            threshold = max(max_pw * 0.5, 50)
            for p in parsed_results:
                bbox = p['bbox']
                w = bbox[2] - bbox[0]
                if w >= threshold:
                    main_col_bboxes.append(((bbox[0] + bbox[2]) / 2, bbox))
            main_col_bboxes.sort(reverse=True)  # 从右到左

    # 修正每列主文
    new_chars = []
    for i, (avg_x, col_key, items) in enumerate(col_info):
        if i >= len(all_groups):
            break
        std_text = all_groups[i]
        ocr_items = sorted(items, key=lambda x: x['row'])

        # 优先使用 parsed_results 中对应主文列的 bbox（更准确，避免累积误差）
        if i < len(main_col_bboxes):
            pbbox = main_col_bboxes[i][1]
            col_bbox = [float(pbbox[0]), float(pbbox[1]), float(pbbox[2]), float(pbbox[3])]
        else:
            col_x1 = min(c['bbox'][0] for c in items)
            col_x2 = max(c['bbox'][2] for c in items)
            col_y1 = min(c['bbox'][1] for c in items)
            col_y2 = max(c['bbox'][3] for c in items)
            col_bbox = [col_x1, col_y1, col_x2, col_y2]

        fixed = fix_column(std_text, ocr_items, col_bbox, len(std_text), img_path)
        for it in fixed:
            it['column'] = i
        new_chars.extend(fixed)

    return new_chars


def main():
    work_dir = Path('王羲之-行书-千字文')
    result_paths = sorted(work_dir.glob('.debug/fatie-0*/result.json'))

    total = 0
    fixed_count = 0
    skipped = 0

    for result_path in result_paths:
        stem = result_path.parent.name
        num = int(stem.split('-')[1])
        if num < 30:
            continue

        chars_path = result_path.parent / 'chars.json'
        img_path = work_dir / f'{stem}.png'

        if not chars_path.exists() or not img_path.exists():
            skipped += 1
            continue

        total += 1

        try:
            new_chars = fix_page_from_annotation(result_path, chars_path, img_path)
            if new_chars is not None:
                with open(chars_path, 'w', encoding='utf-8') as f:
                    json.dump(new_chars, f, ensure_ascii=False, indent=2)
                print(f'{stem}: 已修正 ({len(new_chars)}字)')
                fixed_count += 1
            else:
                print(f'{stem}: 无释文列，跳过')
                skipped += 1
        except Exception as e:
            print(f'{stem}: 异常 - {e}')
            import traceback
            traceback.print_exc()
            skipped += 1

    print(f'\n总计: {total} 页')
    print(f'已修正: {fixed_count} 页')
    print(f'跳过: {skipped} 页')


if __name__ == '__main__':
    main()
