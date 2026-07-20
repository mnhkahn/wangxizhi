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
TEST_IMAGE = "./怀仁集王羲之圣教序/fatie-000.jpg"

def test_basic_ocr():
    """测试基本OCR功能"""
    print("=" * 60)
    print("Test 1: Basic OCR")
    print("=" * 60)

    ocr = CalligraphyOCR()
    result = ocr.recognize_image(
        TEST_IMAGE,
        debug=True,
    )

    print(f"\n结果摘要:")
    print(f"  图像路径: {result['image_path']}")
    print(f"  图像尺寸: {result['image_info']['width']}x{result['image_info']['height']}")
    print(f"  OCR解析项数: {len(result['parsed_results'])}")
    print(f"  总字数: {result['total_chars']}")
    print(f"  列数: {result['column_count']}")

    return result


def test_ocr_details(result):
    """显示详细的OCR结果"""
    print("\n" + "=" * 60)
    print("Test 2: OCR Results Details")
    print("=" * 60)

    print("\n解析后的文本结果:")
    for i, r in enumerate(result['parsed_results'][:10]):
        print(f"  [{i}] 文字: {r['text'][:15]}...")
        if 'bbox' in r:
            print(f"      bbox: {r['bbox']}")

    print(f"\n共 {len(result['parsed_results'])} 个解析项")


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
    test_column_structure(result)
    test_output_files(result)

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
