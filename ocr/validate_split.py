"""
验证脚本：测试单字分割效果
"""

import sys
import os
import json
import argparse
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from ocr import CalligraphyOCR, recognize_calligraphy
import cv2


def validate_split(
    image_path: str,
    known_text: str = None,
    debug: bool = False,
):
    """
    验证分割效果

    Args:
        image_path: 图像路径
        known_text: 已知文字内容（可选）
        debug: 是否输出调试信息

    Returns:
        验证结果字典
    """
    print(f"\n{'='*60}")
    print(f"验证分割效果: {image_path}")
    print(f"{'='*60}")

    # 检查文件是否存在
    if not os.path.exists(image_path):
        print(f"错误: 文件不存在: {image_path}")
        return None

    # 运行识别
    ocr = CalligraphyOCR()
    result = ocr.recognize_image(image_path, debug=debug)

    # 统计信息
    total_chars = result['total_chars']
    column_count = result['column_count']

    print(f"\n识别结果:")
    print(f"  总字数: {total_chars}")
    print(f"  列数: {column_count}")
    print(f"  识别文字: {result['recognized_text'][:50]}...")

    # 如果有已知文字，进行比对
    if known_text:
        expected_count = len(known_text)
        actual_count = total_chars

        print(f"\n与已知文字比对:")
        print(f"  期望字数: {expected_count}")
        print(f"  实际字数: {actual_count}")

        if expected_count == actual_count:
            print(f"  ✓ 字数匹配!")
        else:
            print(f"  ✗ 字数不匹配 (差异: {actual_count - expected_count})")

        # 文字比对
        recognized = result['recognized_text']
        correct = 0
        for i, (exp, act) in enumerate(zip(known_text, recognized)):
            if exp == act:
                correct += 1
            else:
                if i < 20:  # 只显示前20个差异
                    print(f"  位置 {i}: 期望 '{exp}', 实际 '{act}'")

        accuracy = correct / min(len(known_text), len(recognized)) * 100 if recognized else 0
        print(f"  文字准确率: {accuracy:.1f}% ({correct}/{min(len(known_text), len(recognized))})")

    # 分析分割方法分布
    method_stats = {}
    for char_info in result['char_results']:
        method = char_info.get('split_method', 'unknown')
        method_stats[method] = method_stats.get(method, 0) + 1

    print(f"\n分割方法统计:")
    for method, count in method_stats.items():
        print(f"  {method}: {count} 字 ({count/total_chars*100:.1f}%)")

    # 检查 bbox 合理性
    print(f"\nBBox 合理性检查:")
    issues = []

    for char_info in result['char_results']:
        bbox = char_info['bbox']
        char = char_info['char']

        height = bbox[3] - bbox[1]
        width = bbox[2] - bbox[0]

        # 检查宽高比
        if width > 0:
            ratio = height / width
            if ratio < 0.3 or ratio > 5:
                issues.append(f"  异常宽高比: '{char}' ratio={ratio:.2f}")

        # 检查尺寸
        if height < 10 or width < 10:
            issues.append(f"  尺寸过小: '{char}' {width:.0f}x{height:.0f}")

    if issues:
        print(f"  发现 {len(issues)} 个问题:")
        for issue in issues[:10]:  # 只显示前10个
            print(issue)
    else:
        print(f"  ✓ 所有 bbox 尺寸合理")

    return result


def visualize_split(
    result: dict,
    output_path: str = None,
    show_columns: bool = True,
):
    """
    生成可视化图片

    Args:
        result: 识别结果
        output_path: 输出路径
        show_columns: 是否按列着色
    """
    image_path = result['image_path']
    image = cv2.imread(image_path)

    if image is None:
        print(f"无法读取图像: {image_path}")
        return

    if show_columns:
        # 按列着色
        colors = [
            (255, 0, 0), (0, 255, 0), (0, 0, 255),
            (255, 255, 0), (255, 0, 255), (0, 255, 255),
            (128, 0, 255), (255, 128, 0), (128, 255, 0),
            (0, 128, 255), (255, 0, 128), (0, 255, 128),
        ]

        for char_info in result['char_results']:
            color = colors[char_info['column'] % len(colors)]
            bbox = [int(v) for v in char_info['bbox']]
            cv2.rectangle(image, (bbox[0], bbox[1]), (bbox[2], bbox[3]), color, 2)
    else:
        # 统一颜色
        for char_info in result['char_results']:
            bbox = [int(v) for v in char_info['bbox']]
            cv2.rectangle(image, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)

    if output_path:
        cv2.imwrite(output_path, image)
        print(f"\n可视化图片已保存: {output_path}")

    return image


def batch_validate(image_dir: str, debug: bool = False):
    """
    批量验证目录下的所有图片

    Args:
        image_dir: 图片目录
        debug: 是否输出调试信息
    """
    image_dir = Path(image_dir)

    if not image_dir.exists():
        print(f"目录不存在: {image_dir}")
        return

    # 查找所有 jpg 图片
    images = list(image_dir.glob("*.jpg")) + list(image_dir.glob("*.jpeg"))

    if not images:
        print(f"目录下没有找到图片: {image_dir}")
        return

    print(f"\n找到 {len(images)} 张图片")

    results = []
    for img_path in sorted(images)[:5]:  # 只处理前5张
        result = validate_split(str(img_path), debug=debug)
        if result:
            results.append({
                'image': str(img_path),
                'total_chars': result['total_chars'],
                'column_count': result['column_count'],
            })

    # 汇总
    print(f"\n{'='*60}")
    print(f"批量验证汇总")
    print(f"{'='*60}")
    print(f"处理图片数: {len(results)}")
    print(f"总字数: {sum(r['total_chars'] for r in results)}")
    print(f"平均每张字数: {sum(r['total_chars'] for r in results) / len(results):.1f}")


def main():
    parser = argparse.ArgumentParser(description="验证单字分割效果")
    parser.add_argument("image_path", nargs="?", help="图像路径或目录")
    parser.add_argument("--debug", "-d", action="store_true", help="输出调试信息")
    parser.add_argument("--known-text", "-k", help="已知文字内容")
    parser.add_argument("--visualize", "-v", action="store_true", help="生成可视化图片")
    parser.add_argument("--batch", "-b", action="store_true", help="批量验证目录")

    args = parser.parse_args()

    # 默认测试图片
    if not args.image_path:
        args.image_path = "./怀仁集王羲之圣教序/fatie-000.jpg"

    if args.batch:
        batch_validate(args.image_path, debug=args.debug)
    else:
        result = validate_split(
            args.image_path,
            known_text=args.known_text,
            debug=args.debug,
        )

        if result and args.visualize:
            # 生成可视化图片
            output_dir = Path("ocr_output") / Path(args.image_path).stem
            output_path = output_dir / "validate_visualization.jpg"
            visualize_split(result, str(output_path))


if __name__ == "__main__":
    main()
