"""
Test script for Calligraphy OCR
书法拆字识别测试脚本
"""

import sys
import os
import json
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from ocr import CalligraphyOCR, recognize_calligraphy


# 测试图片路径
TEST_IMAGE = "/Users/mnhkahn/code/wangxizhi/怀仁集王羲之圣教序/fatie-000.jpg"

# 已知文字内容（用于校验）
KNOWN_TEXT = (
    "大唐三藏聖教序太宗文皇帝製和福寺沙门懷仁集晋右将军王羲之书"
    "盖闻二仪有像头霞载以含生四时气形滑寒暑以化物是以窺天鑑地庸愚"
)


def test_basic_ocr():
    """测试基本OCR功能"""
    print("=" * 60)
    print("Test 1: Basic OCR")
    print("=" * 60)

    ocr = CalligraphyOCR()
    result = ocr.recognize_image(
        TEST_IMAGE,
        known_text=KNOWN_TEXT,
        debug=True,
    )

    print(f"\n结果摘要:")
    print(f"  图像路径: {result['image_path']}")
    print(f"  图像尺寸: {result['image_info']['width']}x{result['image_info']['height']}")
    print(f"  OCR检测项数: {len(result['ocr_results'])}")
    print(f"  总字数: {result['total_chars']}")
    print(f"  列数: {result['column_count']}")

    return result


def test_ocr_details(result):
    """显示详细的OCR结果"""
    print("\n" + "=" * 60)
    print("Test 2: OCR Results Details")
    print("=" * 60)

    print("\n原始OCR检测结果:")
    for i, r in enumerate(result['ocr_results'][:10]):
        print(f"  [{i}] 文字: {r['text'][:15]}...")
        print(f"      bbox: {r['bbox']}")
        print(f"      置信度: {r['confidence']:.2f}")

    print(f"\n共 {len(result['ocr_results'])} 个检测项")


def test_char_results(result):
    """显示单字结果"""
    print("\n" + "=" * 60)
    print("Test 3: Character Results")
    print("=" * 60)

    print("\n单字识别结果（前30字）:")
    print(f"{'序号':<6} {'列':<4} {'行':<4} {'字':<4} {'bbox':<30}")
    print("-" * 60)

    for r in result['char_results'][:30]:
        print(f"{r['global_index']:<6} {r['column']:<4} {r['row']:<4} {r['char']:<4} {str(r['bbox'])}")

    print(f"\n共 {len(result['char_results'])} 个字")


def test_text_comparison(result):
    """比较识别文字和已知文字"""
    print("\n" + "=" * 60)
    print("Test 4: Text Comparison")
    print("=" * 60)

    recognized = result['recognized_text']
    known = result['known_text']

    print(f"\n识别文字 ({len(recognized)}字):")
    print(f"  {recognized[:50]}...")

    print(f"\n已知文字 ({len(known)}字):")
    print(f"  {known[:50]}...")

    # 计算匹配度
    min_len = min(len(recognized), len(known))
    matches = sum(1 for i in range(min_len) if recognized[i] == known[i])
    accuracy = matches / min_len if min_len > 0 else 0

    print(f"\n匹配度: {matches}/{min_len} = {accuracy:.2%}")

    # 显示差异
    print("\n差异分析:")
    for i in range(min(20, min_len)):
        if recognized[i] != known[i]:
            print(f"  位置{i}: 识别='{recognized[i]}' 已知='{known[i]}'")


def test_column_structure(result):
    """分析列结构"""
    print("\n" + "=" * 60)
    print("Test 5: Column Structure Analysis")
    print("=" * 60)

    columns = {}
    for r in result['char_results']:
        col = r['column']
        if col not in columns:
            columns[col] = []
        columns[col].append(r)

    print(f"\n共 {len(columns)} 列:")
    for col_idx in sorted(columns.keys()):
        col_chars = columns[col_idx]
        text = "".join(c['char'] for c in col_chars)
        print(f"\n列 {col_idx} ({len(col_chars)}字):")
        print(f"  {text}")


def test_output_files(result):
    """检查输出文件"""
    print("\n" + "=" * 60)
    print("Test 6: Output Files")
    print("=" * 60)

    output_dir = Path(result['image_path']).stem
    output_path = Path("ocr_output") / output_dir

    if output_path.exists():
        files = list(output_path.iterdir())
        print(f"\n输出目录: {output_path}")
        print(f"文件列表:")
        for f in sorted(files):
            size = f.stat().st_size
            print(f"  {f.name}: {size:,} bytes")
    else:
        print(f"\n输出目录不存在: {output_path}")


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("Chinese Calligraphy OCR Test")
    print("=" * 60)
    print(f"\n测试图片: {TEST_IMAGE}")

    # 检查文件是否存在
    if not os.path.exists(TEST_IMAGE):
        print(f"错误: 测试图片不存在: {TEST_IMAGE}")
        return

    # 运行测试
    result = test_basic_ocr()
    test_ocr_details(result)
    test_char_results(result)
    test_text_comparison(result)
    test_column_structure(result)
    test_output_files(result)

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
