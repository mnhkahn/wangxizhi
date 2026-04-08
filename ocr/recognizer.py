"""
Main OCR Module for Chinese Calligraphy
书法拆字识别主模块 - 使用 Layout Parsing API
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import cv2

from .config import (
    OUTPUT_DIR,
    SAVE_DEBUG_IMAGES,
)
from .preprocess import ImagePreprocessor
from .api_client import OCRAPIClient


def log_step(step_name: str, data: Any, output_dir: Path, debug: bool = False,
             image: Any = None, bboxes: List = None, labels: List = None,
             title: str = None):
    """记录每一步的结果到JSON文件和图片"""
    step_file = output_dir / f"step_{step_name}.json"
    with open(step_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 保存调试图片
    if image is not None and bboxes:
        colors = [
            (255, 0, 0), (0, 255, 0), (0, 0, 255),
            (255, 255, 0), (255, 0, 255), (0, 255, 255),
        ]
        img_draw = image.copy()
        for i, bbox in enumerate(bboxes):
            color = colors[i % len(colors)]
            x1, y1, x2, y2 = [int(v) for v in bbox]
            cv2.rectangle(img_draw, (x1, y1), (x2, y2), color, 2)
            if labels and i < len(labels):
                cv2.putText(img_draw, str(labels[i]), (x1, y1 - 5),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        step_img = output_dir / f"step_{step_name}.jpg"
        cv2.imwrite(str(step_img), img_draw)

    if debug:
        print(f"[STEP] {step_name} -> {step_file}")


class CalligraphyOCR:
    """书法拆字识别器"""

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_token: Optional[str] = None,
        output_dir: Optional[str] = None,
    ):
        """初始化识别器"""
        self.preprocessor = ImagePreprocessor()
        self.api_client = OCRAPIClient(api_url, api_token) if api_url else OCRAPIClient()
        self.output_dir = Path(output_dir or OUTPUT_DIR)

    def crop_and_save_chars(
        self,
        image: Any,
        char_results: List[Dict[str, Any]],
        image_path: str,
    ) -> List[str]:
        """裁剪单字图片并保存"""
        path_obj = Path(image_path)
        folder_name = path_obj.parent.name

        chars_dir = self.output_dir / path_obj.stem / "chars"
        chars_dir.mkdir(parents=True, exist_ok=True)

        saved_paths = []

        for r in char_results:
            bbox = r["bbox"]
            char = r["char"]

            x1 = max(0, int(bbox[0]))
            y1 = max(0, int(bbox[1]))
            x2 = min(image.shape[1], int(bbox[2]))
            y2 = min(image.shape[0], int(bbox[3]))

            if x2 > x1 and y2 > y1:
                char_img = image[y1:y2, x1:x2]

                filename = f"{folder_name}_{char}.jpg"
                char_path = chars_dir / filename

                cv2.imwrite(str(char_path), char_img)
                saved_paths.append(str(char_path))

        return saved_paths

    def _save_api_images(self, api_result: Dict[str, Any], output_dir: Path, debug: bool = False):
        """
        保存API返回的图片（布局检测图、预处理图等）

        Args:
            api_result: API返回的结果
            output_dir: 输出目录
            debug: 是否输出调试信息
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        saved_images = []

        layout_results = api_result.get("layoutParsingResults", [])
        for page_idx, page_result in enumerate(layout_results):
            # 保存 outputImages 中的图片
            output_images = page_result.get("outputImages", {})
            for img_name, img_url in output_images.items():
                try:
                    import requests
                    img_response = requests.get(img_url, timeout=30)
                    if img_response.status_code == 200:
                        # 根据图片名称确定文件扩展名
                        ext = ".jpg"
                        if "png" in img_url.lower():
                            ext = ".png"
                        filename = output_dir / f"{img_name}{ext}"
                        with open(filename, "wb") as f:
                            f.write(img_response.content)
                        saved_images.append(str(filename))
                        if debug:
                            print(f"[DEBUG] Saved API image: {filename}")
                except Exception as e:
                    if debug:
                        print(f"[DEBUG] Failed to save {img_name}: {e}")

        return saved_images

    def _calculate_luminance(self, b: int, g: int, r: int) -> float:
        """计算像素亮度 (0-255)"""
        return (int(b) + int(g) + int(r)) / 3

    def _estimate_threshold_from_corners(
        self,
        image: Any,
        corner_size: int = 50,
        debug: bool = False,
    ) -> float:
        """根据四角背景亮度自动估算单字拆分阈值"""
        if image is None or len(image.shape) < 2:
            return 200

        height, width = image.shape[:2]
        sample_w = min(corner_size, width)
        sample_h = min(corner_size, height)

        if sample_w <= 0 or sample_h <= 0:
            return 200

        corners = [
            image[0:sample_h, 0:sample_w],
            image[0:sample_h, max(0, width - sample_w):width],
            image[max(0, height - sample_h):height, 0:sample_w],
            image[max(0, height - sample_h):height, max(0, width - sample_w):width],
        ]

        luminance_sum = 0.0
        pixel_count = 0

        for corner in corners:
            if corner.size == 0:
                continue

            if len(corner.shape) == 2:
                luminance_sum += float(corner.astype("float32").sum())
                pixel_count += int(corner.size)
                continue

            pixels = corner.reshape(-1, corner.shape[2])
            for pixel in pixels:
                if len(pixel) >= 4 and int(pixel[3]) == 0:
                    continue

                b = int(pixel[0])
                g = int(pixel[1]) if len(pixel) > 1 else b
                r = int(pixel[2]) if len(pixel) > 2 else b
                luminance_sum += self._calculate_luminance(b, g, r)
                pixel_count += 1

        if pixel_count == 0:
            return 200

        bg_luminance = luminance_sum / pixel_count
        threshold = max(0, min(255, int(bg_luminance)))

        if debug:
            print(
                f"[SPLIT] Auto threshold from corners: "
                f"bg_luminance={bg_luminance:.2f}, threshold={threshold}"
            )

        return threshold

    def _split_column_by_pixels(
        self,
        image: Any,
        col_bbox: List[float],
        threshold: float = 200,
        min_char_height: int = 20,
        padding: int = 2,
        debug: bool = False,
    ) -> List[List[float]]:
        """
        使用像素投影法拆分单列中的单字

        Args:
            image: 原图 (numpy array, BGR格式)
            col_bbox: 列的边界框 [x1, y1, x2, y2]
            threshold: 亮度阈值，低于此值视为文字
            min_char_height: 最小字高度
            padding: 边距

        Returns:
            单字边界框列表 [[x1, y1, x2, y2], ...]
        """
        x1, y1, x2, y2 = [int(v) for v in col_bbox]

        # 确保坐标在图像范围内
        h, w = image.shape[:2]
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(w, x2)
        y2 = min(h, y2)

        if x2 <= x1 or y2 <= y1:
            if debug:
                print(f"[SPLIT] Invalid bbox: [{x1}, {y1}, {x2}, {y2}], skipping")
            return []

        # 裁剪出列区域
        col_region = image[y1:y2, x1:x2]

        # 计算每行的像素投影（亮度累加）
        row_height = y2 - y1
        row_projection = []

        for row in range(row_height):
            dark_count = 0
            for col in range(x2 - x1):
                # BGR 转 亮度
                b, g, r = col_region[row, col]
                lum = self._calculate_luminance(b, g, r)
                if lum < threshold:  # 深色像素（文字）
                    dark_count += 1
            row_projection.append(dark_count)

        # 找到分割点（投影为0或接近0的行）
        segments = []
        in_seg = False
        seg_start = 0

        for i, val in enumerate(row_projection):
            if not in_seg and val > 0:
                in_seg = True
                seg_start = i
            if in_seg and val == 0:
                seg_end = i - 1
                if seg_end - seg_start + 1 >= min_char_height:
                    segments.append([seg_start, seg_end])
                in_seg = False

        # 处理最后一个段
        if in_seg:
            seg_end = len(row_projection) - 1
            if seg_end - seg_start + 1 >= min_char_height:
                segments.append([seg_start, seg_end])

        # 转换为全局坐标
        char_bboxes = []
        for seg_start, seg_end in segments:
            char_y1 = max(0, y1 + seg_start - padding)
            char_y2 = min(h, y1 + seg_end + padding)
            char_bboxes.append([x1, char_y1, x2, char_y2])

        # 日志输出：拆字参数和结果
        if debug:
            print(f"[SPLIT] 列区域 bbox=[{x1}, {y1}, {x2}, {y2}], 尺寸={x2-x1}x{y2-y1}")
            print(f"[SPLIT] threshold={threshold}, min_char_height={min_char_height}")
            print(f"[SPLIT] 检测到 {len(segments)} 个字符段落")
            for i, (s, e) in enumerate(segments):
                print(f"[SPLIT]   段{i}: y={y1+s}~{y1+e} (高{e-s+1}px)")

        return char_bboxes

    def _split_columns_to_chars(
        self,
        parsed_results: List[Dict[str, Any]],
        image: Any = None,
        debug: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        使用列坐标数据和像素投影法拆分单字

        Args:
            parsed_results: Step 3 解析的列数据，每项包含 text, poly, bbox
            image: 原图数据 (numpy array)，用于像素分析

        Returns:
            单字结果列表，每项包含 char, bbox, column, row, global_index
        """
        if not parsed_results:
            return []

        auto_threshold = None
        if image is not None:
            auto_threshold = self._estimate_threshold_from_corners(image, debug=debug)

        # 按列从右到左排序（书法从右向左读）
        sorted_columns = sorted(
            parsed_results,
            key=lambda x: -x["bbox"][2]  # 按 x_max 降序（从右向左）
        )

        char_results = []
        global_index = 0

        for col_idx, col_data in enumerate(sorted_columns):
            text = col_data["text"]
            bbox = col_data["bbox"]

            # 如果有图像数据，使用像素投影法拆分
            if image is not None:
                char_bboxes = self._split_column_by_pixels(
                    image,
                    bbox,
                    threshold=auto_threshold,
                    debug=debug,
                )

                # 将文字分配到各个bbox
                for row_idx, (char, char_bbox) in enumerate(zip(text, char_bboxes)):
                    if row_idx >= len(text):
                        break

                    char_results.append({
                        "char": text[row_idx],
                        "bbox": char_bbox,
                        "column": col_idx,
                        "row": row_idx,
                        "global_index": global_index,
                        "col_text": text,
                        "col_bbox": bbox,
                    })
                    global_index += 1
            else:
                # 回退：使用平均值拆分
                x1, y1, x2, y2 = bbox
                col_height = y2 - y1
                char_count = len(text)

                if char_count == 0:
                    continue

                char_height = col_height / char_count

                for row_idx, char in enumerate(text):
                    char_y1 = y1 + row_idx * char_height
                    char_y2 = y1 + (row_idx + 1) * char_height
                    char_bbox = [x1, char_y1, x2, char_y2]

                    char_results.append({
                        "char": char,
                        "bbox": char_bbox,
                        "column": col_idx,
                        "row": row_idx,
                        "global_index": global_index,
                        "col_text": text,
                        "col_bbox": bbox,
                    })
                    global_index += 1

        return char_results

    def _parse_markdown_result(self, api_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        解析Layout Parsing API返回的结果，提取文字和对应的坐标

        Args:
            api_result: API返回的结果（包含 layoutParsingResults）

        Returns:
            解析后的文字列表，每项包含 text, poly (四边形坐标)
        """
        results = []
        layout_results = api_result.get("layoutParsingResults", [])

        for page_result in layout_results:
            pruned = page_result.get("prunedResult", {})
            spotting_res = pruned.get("spotting_res", {})

            # 优先从 spotting_res 获取 rec_polys 和 rec_texts
            rec_polys = spotting_res.get("rec_polys", [])
            rec_texts = spotting_res.get("rec_texts", [])

            if rec_polys and rec_texts and len(rec_polys) == len(rec_texts):
                # 有精确的坐标信息
                for i, (poly, text) in enumerate(zip(rec_polys, rec_texts)):
                    # poly 是四边形的四个点 [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                    # 转换为 bbox 格式 [x_min, y_min, x_max, y_max]
                    xs = [p[0] for p in poly]
                    ys = [p[1] for p in poly]
                    bbox = [min(xs), min(ys), max(xs), max(ys)]

                    results.append({
                        "text": text,
                        "poly": poly,
                        "bbox": bbox,
                        "index": i,
                    })
                continue

            # 回退：从 markdown 字段获取（无坐标信息）
            markdown_data = page_result.get("markdown", {})
            text = markdown_data.get("text", "")

            if text:
                lines = text.split("\n")
                for i, line in enumerate(lines):
                    line = re.sub(r'!\[.*?\]\(.*?\)', '', line)
                    line = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', line)
                    line = re.sub(r'^#+\s*', '', line)
                    line = line.strip()

                    if line and not line.startswith("!"):
                        results.append({
                            "text": line,
                            "raw": line,
                            "index": i,
                        })
                continue

            # 最后回退：从 parsing_res_list 获取
            parsing_list = pruned.get("parsing_res_list", [])

            for block in parsing_list:
                content = block.get("block_content", "")
                if content:
                    lines = content.split("\n")
                    for line in lines:
                        line = line.strip()
                        if line:
                            results.append({
                                "text": line,
                                "raw": line,
                                "bbox": block.get("block_bbox"),
                                "label": block.get("block_label"),
                            })

        return results

    def recognize_image(
        self,
        image_path: str,
        save_result: bool = True,
        debug: bool = False,
        crop_chars: bool = True,
    ) -> Dict[str, Any]:
        """识别单个图像"""
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        # 创建输出目录
        output_dir = self.output_dir / image_path.stem
        output_dir.mkdir(parents=True, exist_ok=True)

        if debug:
            print(f"[DEBUG] Processing: {image_path}")

        # Step 1: 加载图像
        image = self.preprocessor.load_image(str(image_path))
        image_info = self.preprocessor.get_image_info()
        log_step("01_image_info", image_info, output_dir, debug,
                image=image, bboxes=[], labels=[], title="原图")
        if debug:
            print(f"[DEBUG] Image size: {image_info['width']}x{image_info['height']}")

        # Step 2: 调用Layout Parssing API
        if debug:
            print(f"[DEBUG] Calling Layout Parssing API...")

        response = self.api_client.recognize(str(image_path))

        # 保存API返回的图片（布局检测图、预处理图等）
        self._save_api_images(response, output_dir / "api_images", debug)

        log_step("02_api_response", response, output_dir, debug,
                image=image, bboxes=[], labels=[], title="API调用后")

        # Step 3: 解析API结果 - 获取识别的文字和坐标
        parsed_results = self._parse_markdown_result(response)

        # 绘制带坐标的预览图
        parsed_bboxes = [r.get("bbox", [0,0,0,0]) for r in parsed_results if "bbox" in r]
        parsed_labels = [r["text"][:10] for r in parsed_results if "bbox" in r]
        log_step("03_parsed_text", parsed_results, output_dir, debug,
            image=image, bboxes=parsed_bboxes, labels=parsed_labels,
            title=f"解析的文本 ({len(parsed_results)}列)")

        if debug:
            print(f"[DEBUG] Parsed text results: {len(parsed_results)} items")
            for i, r in enumerate(parsed_results[:10]):
                print(f" [{i}] {r['text'][:30]}...")

        # Step 4: 保存markdown结果到文件
        saved_files = self.api_client.save_results(response, str(output_dir / "api_output"))
        if debug:
            print(f"[DEBUG] Saved {len(saved_files)} files from API")

        # Step 5: 使用列坐标数据和像素投影法拆分单字
        char_results = self._split_columns_to_chars(parsed_results, image=image, debug=debug)

        log_step("05_char_results", char_results, output_dir, debug,
            image=image,
            bboxes=[r["bbox"] for r in char_results],
            labels=[r["char"] for r in char_results],
            title=f"单字结果 ({len(char_results)}字)")

        # Step 6: 生成最终输出
        recognized_text = "".join(r["char"] for r in char_results)
        log_step("06_recognized_text", {"text": recognized_text}, output_dir, debug,
            image=image,
            bboxes=[r["bbox"] for r in char_results],
            labels=[r["char"] for r in char_results],
            title=f"最终识别: {recognized_text[:20]}...")

        result = {
            "image_path": str(image_path),
            "image_info": image_info,
            "recognized_text": recognized_text,
            "parsed_results": parsed_results,
            "char_results": char_results,
            "column_count": max((r["column"] for r in char_results), default=0) + 1 if char_results else 0,
            "total_chars": len(char_results),
            "timestamp": datetime.now().isoformat(),
            "api_output_files": saved_files,
        }

        # Step 7: 保存结果
        if save_result:
            self._save_result(result, debug)

        # Step 8: 裁剪并保存单字图片
        if crop_chars:
            if debug:
                print("[DEBUG] Cropping character images...")
            cropped_paths = self.crop_and_save_chars(image, char_results, str(image_path))
            result["cropped_char_images"] = cropped_paths
            if debug:
                print(f"[DEBUG] Cropped {len(cropped_paths)} character images")

        # Step 9: 保存调试图片
        if debug and SAVE_DEBUG_IMAGES:
            self._save_debug_images(result, image, str(image_path))

        return result

    def _save_result(self, result: Dict[str, Any], debug: bool = False):
        """保存结果到JSON文件"""
        output_dir = self.output_dir / Path(result["image_path"]).stem
        output_dir.mkdir(parents=True, exist_ok=True)

        # 保存完整结果
        json_path = output_dir / "result.json"
        # 移除过大的字段
        save_result = {k: v for k, v in result.items() if k != "api_output_files"}
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(save_result, f, ensure_ascii=False, indent=2)

        if debug:
            print(f"[DEBUG] Result saved to: {json_path}")

        # 保存单字结果（简化版）
        chars_path = output_dir / "chars.json"
        char_data = [
            {
                "char": r["char"],
                "bbox": r["bbox"],
                "column": r["column"],
                "row": r["row"],
                "global_index": r["global_index"],
            }
            for r in result["char_results"]
        ]
        with open(chars_path, "w", encoding="utf-8") as f:
            json.dump(char_data, f, ensure_ascii=False, indent=2)

        # 保存纯文本
        text_path = output_dir / "text.txt"
        with open(text_path, "w", encoding="utf-8") as f:
            f.write(result["recognized_text"])

    def _save_debug_images(
        self,
        result: Dict[str, Any],
        image: Any,
        image_path: str,
    ):
        """保存调试图片"""
        output_dir = self.output_dir / Path(image_path).stem

        # 绘制单字bbox
        char_bboxes = [r["bbox"] for r in result["char_results"]]
        char_texts = [r["char"] for r in result["char_results"]]
        self.preprocessor.draw_bboxes(
            char_bboxes,
            output_path=str(output_dir / "debug_char_bboxes.jpg"),
            color=(255, 0, 0),
        )

        # 绘制带标签的图片
        self.preprocessor.draw_text_labels(
            char_bboxes,
            char_texts,
            output_path=str(output_dir / "debug_with_labels.jpg"),
        )

        # 按列着色
        img_colored = image.copy()
        colors = [
            (255, 0, 0), (0, 255, 0), (0, 0, 255),
            (255, 255, 0), (255, 0, 255), (0, 255, 255),
            (128, 0, 255), (255, 128, 0),
        ]
        for r in result["char_results"]:
            color = colors[r["column"] % len(colors)]
            bbox = [int(v) for v in r["bbox"]]
            cv2.rectangle(img_colored, (bbox[0], bbox[1]), (bbox[2], bbox[3]), color, 2)
        cv2.imwrite(str(output_dir / "debug_columns.jpg"), img_colored)


def recognize_calligraphy(
    image_path: str,
    debug: bool = False,
) -> Dict[str, Any]:
    """便捷函数：识别书法图像"""
    ocr = CalligraphyOCR()
    return ocr.recognize_image(image_path, debug=debug)


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="Chinese Calligraphy OCR")
    parser.add_argument("image_path", help="Path to the calligraphy image")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable debug output")
    parser.add_argument("--output", "-o", help="Output directory")

    args = parser.parse_args()

    ocr = CalligraphyOCR(output_dir=args.output)
    result = ocr.recognize_image(
        args.image_path,
        debug=args.debug,
    )

    print(f"\n识别结果:")
    print(f" 总字数: {result['total_chars']}")
    print(f" 列数: {result['column_count']}")
    print(f" 识别文字: {result['recognized_text'][:50]}...")


if __name__ == "__main__":
    main()
