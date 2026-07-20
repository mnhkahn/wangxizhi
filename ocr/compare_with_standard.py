"""
圣教序 OCR 校对脚本
使用方法: python3 ocr/compare_with_standard.py

说明:
- 读取 ocr/standard_text.txt 作为标准文本（从网上找的原文）
- 读取 王羲之-行书-圣教序/.debug/fatie-*/chars.json 作为 OCR 结果
- 输出替换、缺失、多余字清单
- 自动过滤简繁差异（使用 opencc）
- 自动过滤变体白名单（象/像、耶/邪、罣/挂等）
"""
import json, os
from collections import defaultdict
import difflib
import sys
sys.path.insert(0, 'venv/lib/python3.13/site-packages')
import opencc

converter = opencc.OpenCC('tw2s')

# 读取标准文本
with open(os.path.join(os.path.dirname(__file__), 'standard_text.txt'), 'r', encoding='utf-8') as f:
    standard = f.read()

# 读取每页 OCR
pages = {}
work_dir = '王羲之-行书-圣教序'
for d in sorted(os.listdir(os.path.join(work_dir, '.debug'))):
    if not d.startswith('fatie-'):
        continue
    path = os.path.join(work_dir, '.debug', d, 'chars.json')
    if not os.path.exists(path):
        continue
    data = json.load(open(path, 'r', encoding='utf-8'))
    by_col = defaultdict(list)
    for c in data:
        by_col[c['column']].append(c)
    chars = []
    for col in sorted(by_col.keys()):
        items = sorted(by_col[col], key=lambda c: c['row'])
        for c in items:
            chars.append({
                'char': c['char'],
                'col': c['column'],
                'row': c['row'],
                'bbox': c['bbox'],
                'page': d,
            })
    pages[d] = chars

def is_simp_trad(s, o):
    s_s = converter.convert(s)
    o_s = converter.convert(o)
    return s_s == o_s and s != o

variant_whitelist = {
    ('華', '花'), ('花', '華'),
    ('像', '象'), ('象', '像'),
    ('覩', '睹'), ('睹', '覩'),
    ('邪', '耶'), ('耶', '邪'),
    ('塗', '途'), ('途', '塗'),
    ('閒', '間'), ('間', '閒'),
    ('餐', '飡'), ('飡', '餐'),
    ('焰', '燄'), ('燄', '焰'),
    ('濕', '湿'), ('湿', '濕'),
    ('罷', '罢'), ('罢', '罷'),
    ('罣', '挂'), ('挂', '罣'),
}

def is_variant(s, o):
    return (s, o) in variant_whitelist

def nw_align(s1, s2):
    match, mismatch, gap = 2, -1, -1
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1): dp[i][0] = gap * i
    for j in range(n + 1): dp[0][j] = gap * j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            score = match if s1[i-1] == s2[j-1] or is_simp_trad(s1[i-1], s2[j-1]) else mismatch
            dp[i][j] = max(dp[i-1][j-1] + score, dp[i-1][j] + gap, dp[i][j-1] + gap)
    alignment = []
    i, j = m, n
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            score = match if s1[i-1] == s2[j-1] or is_simp_trad(s1[i-1], s2[j-1]) else mismatch
            if dp[i][j] == dp[i-1][j-1] + score:
                alignment.append((i-1, j-1)); i -= 1; j -= 1; continue
        if i > 0 and dp[i][j] == dp[i-1][j] + gap:
            alignment.append((i-1, None)); i -= 1
        else:
            alignment.append((None, j-1)); j -= 1
    alignment.reverse()
    return alignment

def find_best_window(page_text, standard):
    if not page_text: return None, None, 0
    anchor_len = min(10, len(page_text))
    anchor = page_text[:anchor_len]
    best_ratio, best_s, best_e = 0, 0, 0
    pos = 0
    anchor_positions = []
    while True:
        idx = standard.find(anchor, pos)
        if idx == -1: break
        anchor_positions.append(idx); pos = idx + 1
    if not anchor_positions and anchor_len > 5:
        anchor = page_text[:5]; pos = 0
        while True:
            idx = standard.find(anchor, pos)
            if idx == -1: break
            anchor_positions.append(idx); pos = idx + 1
    for anchor_pos in anchor_positions:
        for window_size in range(len(page_text) - 5, len(page_text) + 15):
            if window_size < 10: continue
            std_s = max(0, anchor_pos - 5)
            std_e = min(len(standard), std_s + window_size + 10)
            std_s = max(0, std_e - window_size - 10)
            seg = standard[std_s:std_e]
            ratio = difflib.SequenceMatcher(None, seg, page_text).ratio()
            if ratio > best_ratio:
                best_ratio, best_s, best_e = ratio, std_s, std_e
    if not anchor_positions:
        step = max(1, (len(standard) - len(page_text)) // 100)
        for i in range(0, max(1, len(standard) - len(page_text) + 1), step):
            window = min(len(page_text) + 10, len(standard) - i)
            ratio = difflib.SequenceMatcher(None, standard[i:i+window], page_text).ratio()
            if ratio > best_ratio:
                best_ratio, best_s, best_e = ratio, i, i + window
        if best_ratio > 0:
            refine_start = max(0, best_s - step)
            refine_end = min(len(standard) - len(page_text) + 1, best_e + step)
            for i in range(refine_start, refine_end):
                window = min(len(page_text) + 10, len(standard) - i)
                ratio = difflib.SequenceMatcher(None, standard[i:i+window], page_text).ratio()
                if ratio > best_ratio:
                    best_ratio, best_s, best_e = ratio, i, i + window
    return best_s, best_e, best_ratio

if __name__ == '__main__':
    print("=== 圣教序 OCR 校对清单 ===\n")
    print("页码 | 列 | 行 | 当前字 | 应改为 | 类型")
    print("-" * 60)

    all_fixes = []
    for page in sorted(pages.keys()):
        page_chars = pages[page]
        page_text = ''.join(c['char'] for c in page_chars)
        std_s, std_e, ratio = find_best_window(page_text, standard)
        if ratio < 0.6 or std_s is None:
            continue
        std_seg = standard[std_s:std_e]
        local_align = nw_align(std_seg, page_text)
        for std_i, ocr_i in local_align:
            if ocr_i is not None:
                c = page_chars[ocr_i]
                if std_i is None:
                    all_fixes.append({'page': page, 'col': c['col'], 'row': c['row'],
                        'current': c['char'], 'correct': '(多余)', 'type': '多余'})
                elif c['char'] != std_seg[std_i] and not is_simp_trad(std_seg[std_i], c['char']) and not is_variant(std_seg[std_i], c['char']):
                    all_fixes.append({'page': page, 'col': c['col'], 'row': c['row'],
                        'current': c['char'], 'correct': std_seg[std_i], 'type': '替换'})
            elif std_i is not None:
                all_fixes.append({'page': page, 'col': '?', 'row': '?',
                    'current': '(缺失)', 'correct': std_seg[std_i], 'type': '缺失'})

    replace_count = 0
    for f in all_fixes:
        if f['type'] == '替换':
            replace_count += 1
            print(f"{f['page']} | {f['col']} | {f['row']} | {f['current']} | {f['correct']} | {f['type']}")
        elif f['type'] == '缺失':
            print(f"{f['page']} | {f['col']} | {f['row']} | (缺失) | {f['correct']} | {f['type']}")
        elif f['type'] == '多余':
            print(f"{f['page']} | {f['col']} | {f['row']} | {f['current']} | (多余) | {f['type']}")

    print(f"\n替换项总数: {replace_count}")

    with open('tmp/修复清单.txt', 'w', encoding='utf-8') as f:
        f.write("页码 | 列 | 行 | 当前字 | 应改为 | 类型\n")
        f.write("-" * 60 + "\n")
        for fix in all_fixes:
            if fix['type'] == '替换':
                f.write(f"{fix['page']} | {fix['col']} | {fix['row']} | {fix['current']} | {fix['correct']} | {fix['type']}\n")
            elif fix['type'] == '缺失':
                f.write(f"{fix['page']} | {fix['col']} | {fix['row']} | (缺失) | {fix['correct']} | {fix['type']}\n")
            elif fix['type'] == '多余':
                f.write(f"{fix['page']} | {fix['col']} | {fix['row']} | {fix['current']} | (多余) | {fix['type']}\n")
