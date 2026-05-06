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
            method_name = "uniform"

        elif self.method == SplitMethod.PIXEL_PROJECTION:
            result = self._pixel_projection_split(image, col_bbox, char_count, debug)
            method_name = "pixel_projection"

        else:  # HYBRID
            result = self._pixel_projection_split(image, col_bbox, char_count, debug)

            if len(result) != char_count:
                if debug:
                    print(f"[SPLIT] 像素投影失败: 期望 {char_count} 个字, 检测到 {len(result)} 个段落")
                result = self._uniform_split(col_bbox, char_count)
                method_name = "uniform_fallback"
            else:
                method_name = "pixel_projection"

        # x 方向收缩，使 bbox 更贴合字的实际宽度
        if image is not None and result:
            shrunk = []
            for bbox in result:
                shrunk.append(self._shrink_x(image, bbox))
            result = shrunk

        return result, method_name

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
        改进的像素投影分割（v5）

        核心改进：
        1. 使用 Otsu 全局阈值代替 adaptiveThreshold，对碑帖拓片效果更好
        2. 去掉过高的 cv 权重，优先相信图像中的实际间隙
        3. 增加 padding + 边缘扩展，避免字的边缘被切掉
        """
        x1, y1, x2, y2 = [int(v) for v in col_bbox]

        if image is None:
            return self._uniform_split(col_bbox, char_count)

        h, w = image.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        if x2 <= x1 or y2 <= y1:
            return self._uniform_split(col_bbox, char_count)

        orig_y1, orig_y2 = y1, y2
        orig_h = orig_y2 - orig_y1
        expected_height = orig_h / char_count

        # 增加 padding，确保包含字的完整边缘
        padding_y = int(expected_height * 0.15)
        y1_padded = max(0, y1 - padding_y)
        y2_padded = min(h, y2 + padding_y)

        col_region = image[y1_padded:y2_padded, x1:x2]

        if len(col_region.shape) == 3:
            gray = cv2.cvtColor(col_region, cv2.COLOR_BGR2GRAY)
        else:
            gray = col_region

        # 检测黑底白字（碑帖拓片）还是白底黑字
        is_dark_bg = float(np.mean(gray)) < 128
        thresh_type = cv2.THRESH_BINARY if is_dark_bg else cv2.THRESH_BINARY_INV

        # 优先使用 Otsu 全局阈值（对书法扫描件效果更好）
        _, binary = cv2.threshold(gray, 0, 255, thresh_type + cv2.THRESH_OTSU)

        # 生成宽松的 binary 用于边缘扩展（覆盖字边缘的渐变色）
        otsu_thresh, _ = cv2.threshold(gray, 0, 255, thresh_type + cv2.THRESH_OTSU)
        if is_dark_bg:
            relaxed_thresh = max(0, int(otsu_thresh * 0.75))
        else:
            relaxed_thresh = min(255, int(otsu_thresh * 1.25))
        _, binary_loose = cv2.threshold(gray, relaxed_thresh, 255, thresh_type)

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

        # 尝试多种搜索范围，选择最优
        best_result = None
        best_score = float('inf')
        best_params = None

        for search_ratio in [0.3, 0.5, 0.7, 1.0]:
            split_points = self._find_split_points(
                smoothed, char_count, search_ratio, expected_height
            )
            if len(split_points) != char_count + 1:
                continue

            heights = [split_points[i+1] - split_points[i] for i in range(char_count)]
            avg_h = np.mean(heights)
            if avg_h <= 0:
                continue

            # 严格验证
            if not self._validate_splits(heights, expected_height, char_count):
                if debug:
                    print(f"[SPLIT] 搜索比例 {search_ratio} 验证失败: heights={heights}")
                continue

            # 评分：分割点处笔画密度越低越好
            split_score = self._score_split(smoothed, split_points)
            score = split_score / (np.max(smoothed) + 1)

            if score < best_score:
                best_score = score
                best_result = split_points
                best_params = search_ratio

        if best_result is None:
            if debug:
                print(f"[SPLIT] Otsu 投影所有参数均验证失败，回退到均匀分割")
            return self._uniform_split(col_bbox, char_count)

        if debug:
            print(f"[SPLIT] 最优搜索比例: {best_params}, score={best_score:.1f}")

        # 基于宽松二值化图像进行边缘扩展，避免字的边缘被切掉
        # 限制扩展幅度，避免相邻字 bbox 严重重叠
        max_expand = max(1, int(expected_height * 0.01))
        char_bboxes = []
        for i in range(char_count):
            seg_start = best_result[i]
            seg_end = best_result[i + 1]

            # 向上扩展：不超过前一个字分割点的一半距离，且不超过 max_expand
            if i > 0:
                max_up = min(max_expand, (seg_start - best_result[i - 1]) // 2)
            else:
                max_up = max_expand
            new_start = seg_start
            for dy in range(1, max_up + 1):
                row = seg_start - dy
                if row < 0:
                    break
                if np.sum(binary_loose[row, center_start:center_end]) > 0:
                    new_start = row
                else:
                    break

            # 向下扩展：不超过后一个字分割点的一半距离，且不超过 max_expand
            if i < char_count - 1:
                max_down = min(max_expand, (best_result[i + 2] - seg_end) // 2)
            else:
                max_down = max_expand
            new_end = seg_end
            for dy in range(1, max_down + 1):
                row = seg_end + dy
                if row >= len(binary_loose):
                    break
                if np.sum(binary_loose[row, center_start:center_end]) > 0:
                    new_end = row
                else:
                    break

            char_y1 = y1_padded + new_start
            char_y2 = y1_padded + new_end
            # 裁剪到原始 col_bbox，避免第一个/最后一个字超出列边界
            char_y1 = max(char_y1, float(orig_y1))
            char_y2 = min(char_y2, float(orig_y2))
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

    def _shrink_x(
        self,
        image: np.ndarray,
        bbox: List[float],
        padding: int = 3,
    ) -> List[float]:
        """根据实际文字像素收缩 bbox 的 x 方向，使其更贴合字的实际宽度。

        对黑底白字（碑帖拓片）和白底黑字均适用。
        """
        x1, y1, x2, y2 = [int(v) for v in bbox]
        h, w = image.shape[:2]
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(w, x2)
        y2 = min(h, y2)

        if x2 <= x1 or y2 <= y1:
            return bbox

        region = image[y1:y2, x1:x2]
        if region.size == 0:
            return bbox

        if len(region.shape) == 3:
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        else:
            gray = region

        is_dark_bg = float(np.mean(gray)) < 128
        thresh_type = cv2.THRESH_BINARY if is_dark_bg else cv2.THRESH_BINARY_INV
        _, binary = cv2.threshold(gray, 0, 255, thresh_type + cv2.THRESH_OTSU)

        # x 方向投影：统计每列的非零像素数
        col_projection = np.sum(binary > 0, axis=0)
        non_zero = np.where(col_projection > 0)[0]

        if len(non_zero) == 0:
            return bbox

        new_x1 = x1 + max(0, non_zero[0] - padding)
        new_x2 = x1 + min(x2 - x1, non_zero[-1] + 1 + padding)

        # 确保不超出原始 bbox 和图像边界
        new_x1 = max(x1, new_x1)
        new_x2 = min(x2, new_x2)

        return [float(new_x1), float(y1), float(new_x2), float(y2)]


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
