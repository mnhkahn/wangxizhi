"""
单字分割模块
支持多种分割策略：均匀分割、像素投影、混合策略

v3 改进（针对行书/草书）：
1. 严格的"真正间隙"检测：只接受连续多行低投影的间隙，避免字内空白被误判
2. 分割结果验证：高度必须在合理范围内，否则回退到均匀分割
3. 更宽的搜索范围以适应字高变化
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
    3. 混合策略：先尝试像素投影（带严格验证），失败则回退到均分
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
        改进的像素投影分割（v3）

        核心改进：
        1. 严格验证分割结果，不合理则回退
        2. "真正间隙"检测：避免把字内空白当成间隙
        3. 更宽的搜索范围以适应行书字高变化
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
        expected_height = col_h / char_count

        # 检测黑底白字（碑帖拓片）还是白底黑字
        is_dark_bg = float(np.mean(gray)) < 128
        thresh_type = cv2.THRESH_BINARY if is_dark_bg else cv2.THRESH_BINARY_INV

        # 尝试多种参数组合，选择最优
        best_result = None
        best_score = float('inf')
        best_params = None

        for window in [11, 21]:
            for search_ratio in [0.3, 0.5, 0.7, 1.0]:
                try:
                    binary = cv2.adaptiveThreshold(
                        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                        thresh_type, window, 2
                    )
                except cv2.error:
                    continue

                # 使用中心 50% 宽度计算投影，减少边缘干扰
                cw = binary.shape[1]
                center_start = max(0, int(cw * 0.25))
                center_end = min(cw, int(cw * 0.75))
                projection = np.sum(binary[:, center_start:center_end], axis=1).astype(float)

                # 平滑
                kernel_size = max(5, int(expected_height / 3))
                if kernel_size % 2 == 0:
                    kernel_size += 1
                kernel = np.ones(kernel_size) / kernel_size
                smoothed = np.convolve(projection, kernel, mode='same')

                split_points = self._find_split_points(
                    smoothed, char_count, search_ratio, expected_height
                )
                if len(split_points) != char_count + 1:
                    continue

                heights = [split_points[i+1] - split_points[i] for i in range(char_count)]
                avg_h = np.mean(heights)
                if avg_h <= 0:
                    continue

                # === 严格验证 ===
                if not self._validate_splits(heights, expected_height, char_count):
                    if debug:
                        print(f"[SPLIT] 参数 window={window}, ratio={search_ratio} 验证失败: heights={heights}")
                    continue

                cv = np.std(heights) / avg_h
                split_score = self._score_split(smoothed, split_points)
                score = cv * 100 + split_score / (np.max(smoothed) + 1)

                if score < best_score:
                    best_score = score
                    best_result = split_points
                    best_params = (window, search_ratio)

        if best_result is None:
            if debug:
                print(f"[SPLIT] 所有投影参数均验证失败，回退到均匀分割")
            return self._uniform_split(col_bbox, char_count)

        if debug:
            print(f"[SPLIT] 最优参数: window={best_params[0]}, search={best_params[1]}, score={best_score:.1f}")

        char_bboxes = []
        for i in range(char_count):
            char_y1 = y1 + best_result[i]
            char_y2 = y1 + best_result[i + 1]
            char_bboxes.append([float(x1), float(char_y1), float(x2), float(char_y2)])

        return char_bboxes

    def _validate_splits(self, heights: List[float], expected_height: float, char_count: int) -> bool:
        """
        验证分割结果是否合理。

        行书/草书特点：字高会有变化，但不会极端。
        拒绝任何 segment 过短（< 55% 预期）或过长（> 165% 预期）的分割。
        """
        if not heights or expected_height <= 0:
            return False

        min_allowed = expected_height * 0.55
        max_allowed = expected_height * 1.65

        for h in heights:
            if h < min_allowed or h > max_allowed:
                return False

        # 变异系数不能太大
        avg_h = np.mean(heights)
        if avg_h <= 0:
            return False
        cv = np.std(heights) / avg_h
        if cv > 0.35:
            return False

        return True

    def _find_split_points(
        self,
        projection: np.ndarray,
        target_count: int,
        search_ratio: float = 0.3,
        expected_height: float = None,
    ) -> List[int]:
        """
        寻找分割点，支持动态搜索范围。

        核心改进：
        1. 首先尝试找到"真正的间隙"（连续多行低投影）
        2. 如果没有真正间隙，使用预期位置而非局部最小值
        """
        length = len(projection)

        if target_count <= 0:
            return [0, length]
        if target_count == 1:
            return [0, length]

        if expected_height is None:
            expected_height = length / target_count

        search_range = int(expected_height * search_ratio)

        # 动态阈值：真正的间隙应该是局部区域的低值
        # 使用局部最大值的 15% 作为阈值
        proj_max = np.max(projection)
        if proj_max <= 0:
            # 全黑或全白，无法分割
            return []

        split_points = [0]
        for i in range(1, target_count):
            center = int(i * expected_height)
            start = max(split_points[-1] + int(expected_height * 0.4),
                       center - search_range)
            end = min(length - int(expected_height * 0.4), center + search_range)

            if start >= end:
                split_points.append(center)
                continue

            local_region = projection[start:end]
            local_max = np.max(local_region)

            # 阈值：局部最大值的 15% 或全局最大值的 10%
            gap_threshold = min(local_max * 0.15, proj_max * 0.10)
            if gap_threshold <= 0:
                gap_threshold = proj_max * 0.05

            # 寻找连续低值区域
            low_mask = local_region < gap_threshold
            if np.any(low_mask):
                # 找到最长的连续低值区域
                best_gap_center = None
                best_gap_width = 0
                current_start = None
                for j, is_low in enumerate(low_mask):
                    if is_low:
                        if current_start is None:
                            current_start = j
                    else:
                        if current_start is not None:
                            width = j - current_start
                            if width > best_gap_width:
                                best_gap_width = width
                                best_gap_center = current_start + width // 2
                            current_start = None
                if current_start is not None:
                    width = len(low_mask) - current_start
                    if width > best_gap_width:
                        best_gap_width = width
                        best_gap_center = current_start + width // 2

                if best_gap_center is not None and best_gap_width >= 2:
                    # 找到了真正的间隙（至少2像素宽）
                    split_points.append(start + best_gap_center)
                    continue

            # 没有找到真正的间隙，回退到预期位置
            # （不寻找局部最小值，避免切入字内部）
            split_points.append(center)

        split_points.append(length)

        # 确保递增且满足最小高度
        adjusted = [split_points[0]]
        for i in range(1, len(split_points) - 1):
            min_y = adjusted[-1] + int(expected_height * 0.4)
            max_y = length - int(expected_height * 0.4) * (target_count - i)
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
