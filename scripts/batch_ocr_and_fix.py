#!/usr/bin/env python3
"""
批量 OCR 识别 + 释文修正
遍历 王羲之-行书-千字文 下所有 fatie-*.png
"""

import struct
import json
import uuid
import sys
import traceback
from pathlib import Path
from difflib import SequenceMatcher

# --- OCR 模块 ---
# 脚本位于 scripts/ 目录，ocr 模块在项目根目录
sys.path.insert(0, str(Path(__file__).parent.parent))
from ocr.recognizer import CalligraphyOCR

# --- PNG Description 读取 ---
def read_png_desc(path):
    with open(path, 'rb') as f:
        header = f.read(8)
        if header != b'\x89PNG\r\n\x1a\n':
            return ''
        while True:
            lb = f.read(4)
            if len(lb) < 4:
                break
            length = struct.unpack('>I', lb)[0]
            ctype = f.read(4)
            data = f.read(length)
            crc = f.read(4)
            if ctype == b'tEXt':
                parts = data.split(b'\x00', 1)
                if parts[0].decode('latin-1') == 'Description':
                    return parts[1].decode('latin-1')
            elif ctype == b'iTXt':
                parts = data.split(b'\x00')
                if len(parts) >= 6 and parts[0].decode('latin-1') == 'Description':
                    return parts[5].decode('utf-8')
    return ''

# --- 释文列过滤 ---
def filter_annotation_columns(columns):
    """过滤释文/注释列（宽度明显偏窄的列）"""
    if not columns or len(columns) <= 1:
        return columns
    widths = [c['bbox'][2] - c['bbox'][0] for c in columns]
    max_width = max(widths)
    threshold = max(max_width * 0.5, 50)
    filtered = [c for c in columns if c['bbox'][2] - c['bbox'][0] >= threshold]
    return filtered if filtered else columns


# --- 释文解析 ---
def parse_desc_cols(desc):
    lines = desc.strip().split('\n')
    cols = []
    for line in lines:
        parts = line.split('\u3000')
        for p in parts:
            p = p.strip()
            if p:
                cols.append(p)
    return cols

# --- 列修正 ---
def fix_column(std_text, ocr_items, col_bbox=None, ocr_text_len=None, image_path=None):
    ocr_items = [dict(item) for item in ocr_items]
    ocr_text = ''.join(item['char'] for item in ocr_items)
    sm = SequenceMatcher(None, std_text, ocr_text)

    new_items = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for k in range(j1, j2):
                item = dict(ocr_items[k])
                item['char'] = std_text[i1 + (k - j1)]
                new_items.append(item)
        elif tag == 'replace':
            std_part = std_text[i1:i2]
            ocr_part = ocr_text[j1:j2]
            # 如果 OCR 字符远多于标准字符（API 把多列合并了），均匀采样
            if len(ocr_part) > len(std_part) and len(std_part) > 0:
                indices = [int((k + 0.5) * len(ocr_part) / len(std_part)) for k in range(len(std_part))]
                for k, idx in enumerate(indices):
                    item = dict(ocr_items[j1 + min(idx, len(ocr_part) - 1)])
                    item['char'] = std_part[k]
                    new_items.append(item)
            else:
                min_len = min(len(std_part), len(ocr_part))
                for k in range(min_len):
                    item = dict(ocr_items[j1 + k])
                    item['char'] = std_part[k]
                    new_items.append(item)
            if len(std_part) > len(ocr_part):
                for k in range(len(ocr_part), len(std_part)):
                    new_items.append({'char': std_part[k], '_insert': True})
        elif tag == 'delete':
            for k in range(i1, i2):
                new_items.append({'char': std_text[k], '_insert': True})
        elif tag == 'insert':
            pass

    # 优先策略：如果有图像和列 bbox，直接用 pixel_projection 重新拆字
    # 这比 SequenceMatcher 的均匀分布更准确，能按图片里实际字的位置截取
    if image_path and col_bbox and len(col_bbox) == 4 and std_text:
        try:
            import cv2
            from ocr.char_splitter import CharSplitter, SplitMethod
            image = cv2.imread(str(image_path))
            if image is not None:
                splitter = CharSplitter(method=SplitMethod.HYBRID, min_char_height=20)
                char_bboxes, method = splitter.split_column(
                    image, col_bbox, std_text, debug=False
                )
                if len(char_bboxes) == len(std_text):
                    real_items = [it for it in new_items if not it.get('_insert')]
                    meta = {'font': '', 'author': '', 'work': '', 'work_dir': ''}
                    if real_items:
                        meta = {k: real_items[0].get(k, '') for k in ['font', 'author', 'work', 'work_dir']}
                    result = []
                    for i, char in enumerate(std_text):
                        result.append({
                            'char': char,
                            'bbox': char_bboxes[i],
                            'id': str(uuid.uuid4()),
                            'row': i,
                        })
                        result[i].update(meta)
                    return result
        except Exception:
            pass

    # 回退：使用原来的均匀分布逻辑
    real_items = [it for it in new_items if not it.get('_insert')]
    if real_items:
        avg_h = sum(it['bbox'][3] - it['bbox'][1] for it in real_items) / len(real_items)
        x1 = min(it['bbox'][0] for it in real_items)
        x2 = max(it['bbox'][2] for it in real_items)
        meta = {k: real_items[0].get(k, '') for k in ['font', 'author', 'work', 'work_dir']}
    else:
        avg_h = 50
        if col_bbox and len(col_bbox) == 4:
            x1, x2 = col_bbox[0], col_bbox[2]
        else:
            x1, x2 = 0, 50
        meta = {'font': '', 'author': '', 'work': '', 'work_dir': ''}

    for it in new_items:
        if not it.get('_insert'):
            it['_anchor_y'] = (it['bbox'][1] + it['bbox'][3]) / 2

    col_y1 = col_bbox[1] if col_bbox and len(col_bbox) == 4 else 0
    col_y2 = col_bbox[3] if col_bbox and len(col_bbox) == 4 else None

    i = 0
    while i < len(new_items):
        if new_items[i].get('_insert'):
            start = i
            while i < len(new_items) and new_items[i].get('_insert'):
                i += 1
            end = i
            n = end - start
            prev_real = new_items[start - 1] if start > 0 and not new_items[start - 1].get('_insert') else None
            next_real = new_items[end] if end < len(new_items) and not new_items[end].get('_insert') else None

            if prev_real and next_real:
                y1 = prev_real['_anchor_y']
                y2 = next_real['_anchor_y']
                spacing = (y2 - y1) / (n + 1)
                for k in range(start, end):
                    cy = y1 + spacing * (k - start + 1)
                    new_items[k]['bbox'] = [x1, cy - avg_h / 2, x2, cy + avg_h / 2]
            elif prev_real:
                for k in range(start, end):
                    cy = prev_real['_anchor_y'] + avg_h * (k - start + 1)
                    new_items[k]['bbox'] = [x1, cy - avg_h / 2, x2, cy + avg_h / 2]
            elif next_real:
                for k in range(start, end):
                    cy = next_real['_anchor_y'] - avg_h * (end - k)
                    new_items[k]['bbox'] = [x1, cy - avg_h / 2, x2, cy + avg_h / 2]
            else:
                if col_y2 is not None:
                    total_h = col_y2 - col_y1
                    spacing = total_h / n
                    for k in range(start, end):
                        cy = col_y1 + spacing * (k - start + 0.5)
                        new_items[k]['bbox'] = [x1, cy - avg_h / 2, x2, cy + avg_h / 2]
                else:
                    for k in range(start, end):
                        cy = avg_h * (k + 0.5)
                        new_items[k]['bbox'] = [x1, cy - avg_h / 2, x2, cy + avg_h / 2]

            for k in range(start, end):
                new_items[k].update(meta)
                new_items[k]['id'] = str(uuid.uuid4())
                del new_items[k]['_insert']
        else:
            i += 1

    for it in new_items:
        it.pop('_anchor_y', None)
    for i, it in enumerate(new_items):
        it['row'] = i
    return new_items

# --- 页面修正 ---
def fix_page(img_path, chars_path):
    desc = read_png_desc(str(img_path))
    if not desc:
        return None
    std_cols = parse_desc_cols(desc)

    # 如果标准正文无效（提示文字），直接返回 None
    if not std_cols:
        return None
    if len(std_cols) == 1 and ('释文暂缺' in std_cols[0] or '暂缺' in std_cols[0]):
        return None

    with open(chars_path, 'r', encoding='utf-8') as f:
        chars = json.load(f)

    # 尝试从 result.json 读取列 bbox 信息（更准确，包含空 text 的列）
    result_path = chars_path.parent / 'result.json'
    parsed_cols = None
    if result_path.exists():
        try:
            with open(result_path, 'r', encoding='utf-8') as f:
                result_data = json.load(f)
            parsed_results = result_data.get('parsed_results', [])
            if parsed_results:
                # 过滤释文列
                parsed_results = filter_annotation_columns(parsed_results)
                # 按 x 从大到小排序，取前 len(std_cols) 列作为主文
                parsed_cols = sorted(parsed_results, key=lambda c: -c['bbox'][2])
                parsed_cols = parsed_cols[:len(std_cols)]
                # 再按 x 从小到大排序（从左到右），与 std_cols 对应
                # std_cols 是从右到左的：第0列是最右列
                # 但 fix_column 期望 ocr_items 是按 y 排序的字符列表
        except Exception:
            parsed_cols = None

    if parsed_cols is not None and len(parsed_cols) == len(std_cols):
        # 使用 result.json 的列 bbox 来分组 chars
        # 按 x 从大到小重新编号列（从右到左）
        new_chars = []
        for col_idx, col_data in enumerate(parsed_cols):
            col_bbox = col_data['bbox']
            col_x1, col_x2 = col_bbox[0], col_bbox[2]
            # 找到 chars 中 x 中心在该列范围内的字符（容差 5px）
            col_chars = []
            for c in chars:
                cx = (c['bbox'][0] + c['bbox'][2]) / 2
                if col_x1 - 5 <= cx <= col_x2 + 5:
                    col_chars.append(c)
            col_chars.sort(key=lambda x: x['row'])

            fixed = fix_column(std_cols[col_idx], col_chars, col_data.get('bbox'), len(col_data.get('text', '')), img_path)
            for it in fixed:
                it['column'] = col_idx
            new_chars.extend(fixed)
        return new_chars

    # 回退：使用 chars.json 中的 column 字段
    columns = {}
    for c in chars:
        columns.setdefault(c['column'], []).append(c)

    col_info = []
    for col_key, items in columns.items():
        avg_x = sum(c['bbox'][0] + c['bbox'][2] for c in items) / (2 * len(items))
        col_info.append((avg_x, col_key))

    col_info.sort(reverse=True)
    selected = col_info[:len(std_cols)]
    selected_col_keys = [k for _, k in selected]
    selected_col_keys.sort()

    if len(selected_col_keys) != len(std_cols):
        return None

    new_chars = []
    for col_idx, col_key in enumerate(selected_col_keys):
        ocr_items = sorted(columns[col_key], key=lambda x: x['row'])
        fixed = fix_column(std_cols[col_idx], ocr_items, None, None, img_path)
        for it in fixed:
            it['column'] = col_idx
        new_chars.extend(fixed)

    return new_chars


def generate_chars_from_ocr(result_data):
    """
    当没有标准正文时，直接从 OCR 的 char_results 过滤释文列生成 chars.json。
    按列宽过滤窄列（释文），重新从右到左编号 column。
    """
    char_results = result_data.get('char_results', [])
    if not char_results:
        return []

    # 按原始 column 分组，计算每列平均宽度
    cols = {}
    for c in char_results:
        cols.setdefault(c['column'], []).append(c)

    widths = []
    for col_key, items in cols.items():
        avg_w = sum(c['bbox'][2] - c['bbox'][0] for c in items) / len(items)
        widths.append((col_key, avg_w))

    if not widths:
        return []

    max_w = max(w for _, w in widths)
    threshold = max(max_w * 0.5, 50)

    # 过滤窄列（释文）
    valid_col_keys = [k for k, w in widths if w >= threshold]
    if not valid_col_keys:
        return []

    # 按 x 坐标从右到左排序（书法从右向左读）
    valid_col_keys.sort(key=lambda k: -cols[k][0]['bbox'][0])

    # 重新编号 column（从右到左为 0, 1, 2...）
    col_mapping = {old: new for new, old in enumerate(valid_col_keys)}

    new_chars = []
    for old_col, new_col in col_mapping.items():
        items = sorted(cols[old_col], key=lambda c: c['row'])
        for row_idx, c in enumerate(items):
            new_chars.append({
                'id': str(uuid.uuid4()),
                'char': c['char'],
                'bbox': c['bbox'],
                'column': new_col,
                'row': row_idx,
            })

    return new_chars


# --- 主程序 ---
def main():
    work_dir = Path('王羲之-行书-千字文')
    png_files = sorted(work_dir.glob('fatie-*.png'))

    ocr = CalligraphyOCR()
    total = len(png_files)
    ok = 0
    fail = 0
    skip = 0

    for idx, png in enumerate(png_files, 1):
        stem = png.stem
        chars_path = work_dir / '.debug' / stem / 'chars.json'

        if chars_path.exists():
            # 已经有结果，直接修正
            try:
                result = fix_page(png, chars_path)
                if result is not None:
                    with open(chars_path, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                    print(f'[{idx}/{total}] {stem}: 已修正')
                    ok += 1
                else:
                    # 没有标准正文，直接从 result.json 过滤释文列生成
                    result_path = chars_path.parent / 'result.json'
                    if result_path.exists():
                        with open(result_path, 'r', encoding='utf-8') as f:
                            result_data = json.load(f)
                        chars = generate_chars_from_ocr(result_data)
                        if chars:
                            with open(chars_path, 'w', encoding='utf-8') as f:
                                json.dump(chars, f, ensure_ascii=False, indent=2)
                            print(f'[{idx}/{total}] {stem}: OCR过滤释文 ({len(chars)}字)')
                            ok += 1
                        else:
                            print(f'[{idx}/{total}] {stem}: 无正文可生成')
                            fail += 1
                    else:
                        print(f'[{idx}/{total}] {stem}: 修正失败（无Description）')
                        fail += 1
            except Exception as e:
                print(f'[{idx}/{total}] {stem}: 修正异常 - {e}')
                fail += 1
            continue

        # 如果 result.json 存在但 chars.json 不存在，从 result.json 重建 chars.json 再修正
        result_path = chars_path.parent / 'result.json'
        if result_path.exists():
            try:
                with open(result_path, 'r', encoding='utf-8') as f:
                    result_data = json.load(f)
                char_results = result_data.get('char_results', [])
                if char_results:
                    # 从 char_results 重建 chars.json
                    temp_chars = []
                    for r in char_results:
                        temp_chars.append({
                            'id': str(uuid.uuid4()),
                            'char': r.get('char', ''),
                            'bbox': r.get('bbox', [0, 0, 0, 0]),
                            'column': r.get('column', 0),
                            'row': r.get('row', 0),
                        })
                    with open(chars_path, 'w', encoding='utf-8') as f:
                        json.dump(temp_chars, f, ensure_ascii=False, indent=2)
                    # 修正
                    fixed = fix_page(png, chars_path)
                    if fixed is not None:
                        with open(chars_path, 'w', encoding='utf-8') as f:
                            json.dump(fixed, f, ensure_ascii=False, indent=2)
                        print(f'[{idx}/{total}] {stem}: 从result修正完成 ({len(fixed)}字)')
                        ok += 1
                        continue
                    else:
                        # 没有标准正文，直接过滤释文列生成
                        chars = generate_chars_from_ocr(result_data)
                        if chars:
                            with open(chars_path, 'w', encoding='utf-8') as f:
                                json.dump(chars, f, ensure_ascii=False, indent=2)
                            print(f'[{idx}/{total}] {stem}: OCR过滤释文 ({len(chars)}字)')
                            ok += 1
                            continue
            except Exception as e:
                print(f'[{idx}/{total}] {stem}: 从result修正异常 - {e}')
                # 继续到OCR分支

        # 需要 OCR
        print(f'[{idx}/{total}] {stem}: 开始识别...')
        try:
            result = ocr.recognize_image(str(png), save_result=True, debug=False, crop_chars=False)
            if result['total_chars'] == 0:
                print(f'[{idx}/{total}] {stem}: 识别结果为空')
                fail += 1
                continue

            # 修正
            fixed = fix_page(png, chars_path)
            if fixed is not None:
                with open(chars_path, 'w', encoding='utf-8') as f:
                    json.dump(fixed, f, ensure_ascii=False, indent=2)
                print(f'[{idx}/{total}] {stem}: 识别+修正完成 ({result["total_chars"]}字)')
                ok += 1
            else:
                # 没有标准正文，直接过滤释文列生成
                chars = generate_chars_from_ocr(result)
                if chars:
                    with open(chars_path, 'w', encoding='utf-8') as f:
                        json.dump(chars, f, ensure_ascii=False, indent=2)
                    print(f'[{idx}/{total}] {stem}: OCR过滤释文 ({len(chars)}字)')
                    ok += 1
                else:
                    print(f'[{idx}/{total}] {stem}: 识别完成但无正文')
                    fail += 1
        except Exception as e:
            print(f'[{idx}/{total}] {stem}: 异常 - {e}')
            traceback.print_exc()
            fail += 1

    print(f'\n=== 完成 ===')
    print(f'总计: {total} 页')
    print(f'成功: {ok} 页')
    print(f'失败: {fail} 页')

if __name__ == '__main__':
    main()
