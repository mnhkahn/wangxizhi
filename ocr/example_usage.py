"""
书法拆字识别使用示例
Usage example for Chinese Calligraphy OCR
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from ocr import CalligraphyOCR, recognize_calligraphy


def example_basic_usage():
    """示例1: 基本用法 - 识别单个图片"""
    print("=" * 60)
    print("示例1: 基本用法")
    print("=" * 60)

    # 测试图片路径
    image_path = str(project_root / "怀仁集王羲之圣教序" / "fatie-000.jpg")

    # 使用便捷函数
    result = recognize_calligraphy(image_path, debug=True)

    print(f"\n识别完成!")
    print(f"  总字数: {result['total_chars']}")
    print(f"  列数: {result['column_count']}")
    print(f"  完整文字:\n  {result['recognized_text'][:50]}...")

def example_access_char_bboxes():
    """示例2: 访问每个字的bbox信息"""
    print("\n" + "=" * 60)
    print("示例3: 访问单字Bbox信息")
    print("=" * 60)

    ocr = CalligraphyOCR()
    result = ocr.recognize_image(
        str(project_root / "怀仁集王羲之圣教序" / "fatie-000.jpg"),
        debug=False
    )

    print("\n前五字的详细信息:")
    print(f"{'字':<6} {'列':<4} {'行':<4} {'bbox (x1,y1,x2,y2)':<30}")
    print("-" * 50)

    for char_info in result['char_results'][:5]:
        char = char_info['char']
        col = char_info['column']
        row = char_info['row']
        bbox = char_info['bbox']
        print(f"{char:<6} {col:<4} {row:<4} {str(bbox[:4])}")


def example_process_single_column():
    """示例3: 按列处理文字"""
    print("\n" + "=" * 60)
    print("示例4: 按列处理文字")
    print("=" * 60)

    result = recognize_calligraphy(
        str(project_root / "怀仁集王羲之圣教序" / "fatie-000.jpg"),
        debug=False
    )

    # 按列分组
    columns = {}
    for char_info in result['char_results']:
        col = char_info['column']
        if col not in columns:
            columns[col] = []
        columns[col].append(char_info)

    print("\n按列显示文字:")
    for col_idx in sorted(columns.keys())[:4]:  # 只显示前4列
        chars = [c['char'] for c in columns[col_idx]]
        text = ''.join(chars)
        print(f"  列{col_idx}: {text}")


if __name__ == "__main__":
    # 运行所有示例
    example_basic_usage()
    example_access_char_bboxes()
    example_process_single_column()

    print("\n" + "=" * 60)
    print("所有示例运行完成!")
    print("=" * 60)
