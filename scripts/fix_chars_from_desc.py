import struct
import json
import uuid
from pathlib import Path
from difflib import SequenceMatcher

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

def fix_column(std_text, ocr_items):
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
    
    real_items = [it for it in new_items if not it.get('_insert')]
    if real_items:
        avg_h = sum(it['bbox'][3] - it['bbox'][1] for it in real_items) / len(real_items)
        x1 = min(it['bbox'][0] for it in real_items)
        x2 = max(it['bbox'][2] for it in real_items)
        meta = {k: real_items[0].get(k, '') for k in ['font', 'author', 'work', 'work_dir']}
    else:
        avg_h = 50
        x1, x2 = 0, 50
        meta = {'font': '', 'author': '', 'work': '', 'work_dir': ''}
    
    for it in new_items:
        if not it.get('_insert'):
            it['_anchor_y'] = (it['bbox'][1] + it['bbox'][3]) / 2
    
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

def fix_page(img_path, chars_path):
    desc = read_png_desc(str(img_path))
    if not desc:
        return None
    std_cols = parse_desc_cols(desc)
    
    with open(chars_path, 'r', encoding='utf-8') as f:
        chars = json.load(f)
    
    columns = {}
    for c in chars:
        columns.setdefault(c['column'], []).append(c)
    
    # 按 x 坐标排序（从右到左），取最右边的 len(std_cols) 列
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
        fixed = fix_column(std_cols[col_idx], ocr_items)
        for it in fixed:
            it['column'] = col_idx
        new_chars.extend(fixed)
    
    return new_chars

work_dir = Path('王羲之-行书-千字文')
png_files = sorted(work_dir.glob('fatie-*.png'))

fixed_count = 0
skipped = []
for png in png_files:
    stem = png.stem
    chars_path = work_dir / '.debug' / stem / 'chars.json'
    if not chars_path.exists():
        skipped.append(f'{stem}: 无 chars.json')
        continue
    
    result = fix_page(png, chars_path)
    if result is None:
        skipped.append(f'{stem}: 无 Description 或列数不匹配')
        continue
    
    with open(chars_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    fixed_count += 1

print(f'修正完成: {fixed_count} 页')
if skipped:
    print(f'跳过: {len(skipped)} 页')
    for s in skipped[:10]:
        print(f'  {s}')
