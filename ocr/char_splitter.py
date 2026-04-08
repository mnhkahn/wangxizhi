"""
单字分割模块
支持多种分割策略：均匀分割、像素投影、混合策略
"""

from typing import List, Tuple, Optional, Dict, Any
from enum import Enum
import cv2
import numpy as np


class SplitMethod(Enum):
    """分割方法枚举"""
    UNIFORM = "uniform"           # 均匀分割
    PIXEL_PROJECTION = "pixel"    # 像素投影
    HYBRID = "hybrid"             # 混合策略（推荐）


class CharSplitter:
    """
    单字分割器

    支持三种分割策略：
    1. 均匀分割：根据字数均分列高度，适合书法文字间隔均匀的特点
    2. 像素投影：基于图像像素分析，适合背景均匀的图像
    3. 混合策略：先尝试像素投影，失败则回退到均分
    """

    def __init__(
        self,
        method: SplitMethod = SplitMethod.HYBRID,
        min_char_height: int = 20,
        margin_ratio: float = 0.05,
        projection_threshold_ratio: float = 0.1,
    ):
        """
        初始化分割器

        Args:
            method: 分割方法
            min_char_height: 最小字高度（像素）
            margin_ratio: 均分边距比例
            projection_threshold_ratio: 投影阈值比例
        """
        self.method = method
        self.min_char_height = min_char_height
        self.margin_ratio = margin_ratio
        self.projection_threshold_ratio = projection_threshold_ratio

    def split_column(
        self,
        image: np.ndarray,
        col_bbox: List[float],
        text: str,
        debug: bool = False,
    ) -> Tuple[List[List[float]], str]:
        """
        分割单列中的单字

        Args:
            image: 原图 (numpy array, BGR格式)
            col_bbox: 列边界框 [x1, y1, x2, y2]
            text: 该列的文字内容
            debug: 是否输出调试信息

        Returns:
            元组 (单字边界框列表, 使用的分割方法名称)
        """
        char_count = len(text)
        if char_count == 0:
            return [], "none"

        if self.method == SplitMethod.UNIFORM:
            result = self._uniform_split(col_bbox, char_count)
            return result, "uniform"

        elif self.method == SplitMethod.PIXEL_PROJECTION:
            result = self._pixel_projection_split(image, col_bbox, char_count, debug)
            return result, "pixel_projection"

        else:  # HYBRID
            # 先尝试像素投影
            result = self._pixel_projection_split(image, col_bbox, char_count, debug)

            # 验证结果：如果分割数量与文字数量不匹配，回退到均分
            if len(result) != char_count:
                if debug:
                    print(f"[SPLIT] 像素投影失败: 期望 {char_count} 个字, 检测到 {len(result)} 个段落")
                result = self._uniform_split(col_bbox, char_count)
                return result, "uniform_fallback"

            return result, "pixel_projection"

    def _uniform_split(
        self,
        bbox: List[float],
        char_count: int,
    ) -> List[List[float]]:
        """
        均匀分割

        书法特点：文字间隔相对均匀，均分效果可接受

        Args:
            bbox: 列边界框 [x1, y1, x2, y2]
            char_count: 字数

        Returns:
            单字边界框列表
        """
        if char_count <= 0:
            return []

        x1, y1, x2, y2 = bbox
        height = y2 - y1

        # 计算边距（处理书法文字的微小变化）
        margin = height * self.margin_ratio
        effective_height = height - margin * 2

        char_height = effective_height / char_count

        char_bboxes = []
        for i in range(char_count):
            char_y1 = y1 + margin + i * char_height
            char_y2 = y1 + margin + (i + 1) * char_height
            char_bboxes.append([x1, char_y1, x2, char_y2])

        return char_bboxes

    def _pixel_projection_split(
        self,
        image: np.ndarray,
        col_bbox: List[float],
        char_count: int,
        debug: bool = False,
    ) -> List[List[float]]:
        """
        改进的像素投影分割

        改进点：
        1. 自适应二值化（替代固定阈值）
        2. 高斯平滑投影曲线
        3. 寻找局部最小值作为分割点
        4. 使用字数作为约束

        Args:
            image: 原图
            col_bbox: 列边界框
            char_count: 字数
            debug: 是否输出调试信息

        Returns:
            单字边界框列表
        """
        x1, y1, x2, y2 = [int(v) for v in col_bbox]

        # 边界检查
        if image is None:
            return self._uniform_split(col_bbox, char_count)

        h, w = image.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        if x2 <= x1 or y2 <= y1:
            return self._uniform_split(col_bbox, char_count)

        # 裁剪列区域
        col_region = image[y1:y2, x1:x2]

        # 转灰度
        if len(col_region.shape) == 3:
            gray = cv2.cvtColor(col_region, cv2.COLOR_BGR2GRAY)
        else:
            gray = col_region

        # 自适应二值化
        try:
            binary = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV, 11, 2
            )
        except cv2.error:
            # 如果自适应二值化失败，使用固定阈值
            _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY_INV)

        # 水平投影
        projection = np.sum(binary, axis=1).astype(float)

        # 平滑投影曲线
        kernel_size = max(5, int((y2 - y1) / char_count / 4))
        kernel = np.ones(kernel_size) / kernel_size
        smoothed = np.convolve(projection, kernel, mode='same')

        # 寻找分割点
        split_points = self._find_split_points(smoothed, char_count, debug)

        if len(split_points) != char_count + 1:
            # 分割点数量不匹配
            return self._uniform_split(col_bbox, char_count)

        # 生成 bbox
        char_bboxes = []
        for i in range(char_count):
            char_y1 = y1 + split_points[i]
            char_y2 = y1 + split_points[i + 1]
            char_bboxes.append([float(x1), float(char_y1), float(x2), float(char_y2)])

        return char_bboxes

    def _find_split_points(
        self,
        projection: np.ndarray,
        target_count: int,
        debug: bool = False,
    ) -> List[int]:
        """
        寻找分割点

        策略：找到 target_count + 1 个分割点（包括起点和终点）

        Args:
            projection: 投影曲线
            target_count: 目标字数
            debug: 是否输出调试信息

        Returns:
            分割点列表（y坐标）
        """
        length = len(projection)

        if target_count <= 0:
            return [0, length]

        if target_count == 1:
            return [0, length]

        # 计算期望的字符高度
        expected_height = length / target_count

        split_points = [0]

        for i in range(1, target_count):
            # 在期望位置附近搜索局部最小值
            center = int(i * expected_height)
            search_range = int(expected_height * 0.3)

            start = max(split_points[-1] + self.min_char_height,
                       center - search_range)
            end = min(length - self.min_char_height, center + search_range)

            if start >= end:
                split_points.append(center)
                continue

            # 找局部最小值
            local_region = projection[start:end]
            local_min_idx = np.argmin(local_region)
            split_points.append(start + local_min_idx)

        split_points.append(length)

        if debug:
            print(f"[SPLIT] 找到 {len(split_points)} 个分割点: {split_points}")

        return split_points


def split_column_to_chars(
    image: np.ndarray,
    col_bbox: List[float],
    text: str,
    method: str = "hybrid",
    debug: bool = False,
) -> Tuple[List[List[float]], str]:
    """
    便捷函数：分割单列中的单字

    Args:
        image: 原图
        col_bbox: 列边界框
        text: 文字内容
        method: 分割方法 (uniform, pixel, hybrid)
        debug: 是否输出调试信息

    Returns:
        元组 (单字边界框列表, 使用的分割方法名称)
    """
    method_enum = SplitMethod(method)
    splitter = CharSplitter(method=method_enum)
    return splitter.split_column(image, col_bbox, text, debug)
