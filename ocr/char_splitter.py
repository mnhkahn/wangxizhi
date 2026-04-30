"""
单字分割模块
支持多种分割策略：均匀分割、像素投影、混合策略

v2 改进：
1. 多参数组合尝试（窗口大小、搜索范围），自动选优
2. 分割稳定性评分（变异系数 + 分割点笔画密度）
3. 保留所有原有接口
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
            projection_threshold_ratio: 投影阈值比例（保留兼容，不再使用）
        """
        self.method = method
        self.min_char_height = min_char_height
        self.margin_ratio = margin_ratio

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
            result = self._pixel_projection_split(image, col_bbox, char_count, debug)

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
        """均匀分割"""
        if char_count <= 0:
            return []

        x1, y1, x2, y2 = bbox
        height = y2 - y1
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
        1. 尝试多种窗口大小（11, 21）和搜索范围（30%, 50%）
        2. 选择变异系数最低 + 分割点笔画密度最低的组合
        3. 保留自适应高斯二值化（已验证对书法有效）
        """
        x1, y1, x2, y2 = [int(v) for v in col_bbox]

        if image is None:
            return self._uniform_split(col_bbox, char_count)

        h, w = image.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        if x2 <= x1 or y2 <= y1:
            return self._uniform_split(col_bbox, char_count)

        col_region = image[y1:y2, x1:x2]

        if len(col_region.shape) == 3:
            gray = cv2.cvtColor(col_region, cv2.COLOR_BGR2GRAY)
        else:
            gray = col_region

        col_h = y2 - y1

        # 尝试多种参数组合，选择最优
        best_result = None
        best_score = float('inf')
        best_params = None

        # 检测黑底白字（碑帖拓片）还是白底黑字
        is_dark_bg = float(np.mean(gray)) < 128
        thresh_type = cv2.THRESH_BINARY if is_dark_bg else cv2.THRESH_BINARY_INV

        for window in [11, 21]:
            for search_ratio in [0.3, 0.5]:
                try:
                    binary = cv2.adaptiveThreshold(
                        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                        thresh_type, window, 2
                    )
                except cv2.error:
                    continue

                projection = np.sum(binary, axis=1).astype(float)

                # 平滑
                kernel_size = max(5, int(col_h / char_count / 4))
                if kernel_size % 2 == 0:
                    kernel_size += 1
                kernel = np.ones(kernel_size) / kernel_size
                smoothed = np.convolve(projection, kernel, mode='same')

                split_points = self._find_split_points(
                    smoothed, char_count, search_ratio
                )
                if len(split_points) != char_count + 1:
                    continue

                heights = [split_points[i+1] - split_points[i] for i in range(char_count)]
                avg_h = np.mean(heights)
                if avg_h <= 0:
                    continue
                cv = np.std(heights) / avg_h

                # 评分：CV 越低越好，分割点处笔画密度越低越好
                split_score = self._score_split(smoothed, split_points)
                score = cv * 100 + split_score / (np.max(smoothed) + 1)

                if score < best_score:
                    best_score = score
                    best_result = split_points
                    best_params = (window, search_ratio)

        if best_result is None:
            return self._uniform_split(col_bbox, char_count)

        if debug:
            print(f"[SPLIT] 最优参数: window={best_params[0]}, search={best_params[1]}, score={best_score:.1f}")

        char_bboxes = []
        for i in range(char_count):
            char_y1 = y1 + best_result[i]
            char_y2 = y1 + best_result[i + 1]
            char_bboxes.append([float(x1), float(char_y1), float(x2), float(char_y2)])

        return char_bboxes

    def _find_split_points(
        self,
        projection: np.ndarray,
        target_count: int,
        search_ratio: float = 0.3,
    ) -> List[int]:
        """寻找分割点，支持动态搜索范围"""
        length = len(projection)

        if target_count <= 0:
            return [0, length]
        if target_count == 1:
            return [0, length]

        expected_height = length / target_count
        search_range = int(expected_height * search_ratio)

        split_points = [0]
        for i in range(1, target_count):
            center = int(i * expected_height)
            start = max(split_points[-1] + self.min_char_height,
                       center - search_range)
            end = min(length - self.min_char_height, center + search_range)

            if start >= end:
                split_points.append(center)
                continue

            local_region = projection[start:end]
            local_min_idx = np.argmin(local_region)
            split_points.append(start + local_min_idx)

        split_points.append(length)

        # 确保递增且满足最小高度
        adjusted = [split_points[0]]
        for i in range(1, len(split_points) - 1):
            min_y = adjusted[-1] + self.min_char_height
            max_y = length - self.min_char_height * (target_count - i)
            if split_points[i] < min_y:
                split_points[i] = min_y
            elif split_points[i] > max_y:
                split_points[i] = max_y
            adjusted.append(split_points[i])
        adjusted.append(split_points[-1])

        return adjusted

    def _score_split(self, projection, split_points):
        """评分：分割点处笔画密度越低越好"""
        score = 0
        for sp in split_points[1:-1]:
            w = 3
            start = max(0, sp - w)
            end = min(len(projection), sp + w + 1)
            score += np.mean(projection[start:end])
        return score


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
