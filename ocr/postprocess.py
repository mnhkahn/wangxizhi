"""
Postprocessing Module for Chinese Calligraphy OCR
书法OCR后处理模块：竖排文字重排序 + 单字bbox计算
"""

from typing import List, Dict, Any, Tuple, Optional
import numpy as np


class CalligraphyPostprocessor:
    """
    书法作品后处理器
    处理竖排文字：从右上角开始，从右向左、从上往下
    """

    def __init__(
        self,
        direction: str = "right_to_left",
        column_direction: str = "top_to_bottom",
    ):
        """
        初始化后处理器

        Args:
            direction: 列排列方向 ("right_to_left" 或 "left_to_right")
            column_direction: 列内文字排列方向 ("top_to_bottom" 或 "bottom_to_top")
        """
        self.direction = direction
        self.column_direction = column_direction

    def process(
        self,
        ocr_results: List[Dict[str, Any]],
        image_width: Optional[int] = None,
        image_height: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        处理OCR结果：重排序并计算单字bbox

        Args:
            ocr_results: 原始OCR结果
            image_width: 图像宽度
            image_height: 图像高度

        Returns:
            处理后的结果，每个元素包含:
            - char: 单字
            - bbox: [x1, y1, x2, y2]
            - column: 列索引（从右往左，0开始）
            - row: 行索引（从上往下，0开始）
        """
        if not ocr_results:
            return []

        # Step 1: 分析列结构
        columns = self._analyze_columns(ocr_results)

        # Step 2: 对列进行排序（从右向左）
        sorted_columns = self._sort_columns(columns)

        # Step 3: 对每列内的文字进行排序（从上往下）
        for col in sorted_columns:
            col["items"] = self._sort_column_items(col["items"])

        # Step 4: 合并所有文字并生成单字结果
        char_results = []
        global_char_index = 0

        for col_idx, col in enumerate(sorted_columns):
            col_items = col["items"]

            # 生成单字bbox
            for row_idx, item in enumerate(col_items):
                text = item["text"]
                bbox = item["bbox"]

                # 将bbox均分给每个字
                char_bboxes = self._split_bbox_to_chars(
                    bbox, len(text), col_idx, row_idx
                )

                for char_idx, (char, char_bbox) in enumerate(zip(text, char_bboxes)):
                    char_results.append({
                        "char": char,
                        "bbox": char_bbox,
                        "column": col_idx,
                        "row": row_idx,
                        "char_in_text": char_idx,
                        "global_index": global_char_index,
                    })
                    global_char_index += 1

        return char_results

    def _analyze_columns(
        self,
        ocr_results: List[Dict[str, Any]],
        merge_threshold: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """
        分析OCR结果中的列结构

        竖排书法中，每个OCR检测项可能是一列或一列的一部分

        Args:
            ocr_results: 原始OCR结果
            merge_threshold: 合并阈值（相对于列宽的比例）

        Returns:
            列列表，每列包含items列表
        """
        if not ocr_results:
            return []

        # 计算每个检测项的中心x坐标和尺寸
        items_with_center = []
        for item in ocr_results:
            bbox = item["bbox"]
            center_x = (bbox[0] + bbox[2]) / 2
            center_y = (bbox[1] + bbox[3]) / 2
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            item["_center_x"] = center_x
            item["_center_y"] = center_y
            item["_width"] = width
            item["_height"] = height
            items_with_center.append(item)

        # 计算平均列宽
        avg_width = sum(item["_width"] for item in items_with_center) / len(items_with_center)

        # 按x坐标分组（同一列的项x坐标相近）
        sorted_items = sorted(items_with_center, key=lambda x: x["_center_x"])

        columns = []
        current_column = None

        for item in sorted_items:
            if current_column is None:
                current_column = {"items": [item], "_center_x": item["_center_x"]}
            else:
                # 判断是否属于同一列：如果x坐标差异小于平均宽度的阈值倍数
                threshold = avg_width * merge_threshold
                if abs(item["_center_x"] - current_column["_center_x"]) < threshold:
                    current_column["items"].append(item)
                    # 更新列的中心x坐标（取平均）
                    total_items = len(current_column["items"])
                    current_column["_center_x"] = (
                        current_column["_center_x"] * (total_items - 1) + item["_center_x"]
                    ) / total_items
                else:
                    # 新列
                    columns.append(current_column)
                    current_column = {"items": [item], "_center_x": item["_center_x"]}

        if current_column:
            columns.append(current_column)

        # 计算每列的合并bbox
        for col in columns:
            all_bboxes = [item["bbox"] for item in col["items"]]
            x1 = min(bbox[0] for bbox in all_bboxes)
            y1 = min(bbox[1] for bbox in all_bboxes)
            x2 = max(bbox[2] for bbox in all_bboxes)
            y2 = max(bbox[3] for bbox in all_bboxes)
            col["bbox"] = [x1, y1, x2, y2]
            col["text"] = "".join(item["text"] for item in col["items"])

        return columns

    def _sort_columns(self, columns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        对列进行排序

        Args:
            columns: 列列表

        Returns:
            排序后的列列表
        """
        if self.direction == "right_to_left":
            # 从右向左：x坐标大的排前面（使用右边界x2）
            return sorted(columns, key=lambda col: -col["bbox"][2])
        else:
            # 从左向右：x坐标小的排前面
            return sorted(columns, key=lambda col: col["bbox"][0])

    def _sort_column_items(
        self, items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        对列内的项进行排序

        Args:
            items: 项列表

        Returns:
            排序后的项列表
        """
        if self.column_direction == "top_to_bottom":
            # 从上往下：y坐标小的排前面
            return sorted(items, key=lambda item: item["bbox"][1])
        else:
            # 从下往上：y坐标大的排前面
            return sorted(items, key=lambda item: -item["bbox"][1])

    def _split_bbox_to_chars(
        self,
        bbox: List[float],
        char_count: int,
        col_idx: int,
        row_idx: int,
        margin_ratio: float = 0.1,
    ) -> List[List[float]]:
        """
        将bbox均分给每个字

        对于竖排书法，bbox的高度通常包含多个字

        Args:
            bbox: 边界框 [x1, y1, x2, y2]
            char_count: 字数
            col_idx: 列索引
            row_idx: 行索引
            margin_ratio: 边距比例，用于处理书法文字的微小变化

        Returns:
            每个字的边界框列表
        """
        if char_count <= 0:
            return []

        x1, y1, x2, y2 = bbox
        width = x2 - x1
        height = y2 - y1

        # 计算边距，处理书法文字的微小变化
        margin = height * margin_ratio / (char_count + 1)
        effective_height = height - margin * (char_count + 1)

        # 假设竖排文字，高度均分（考虑边距）
        char_height = effective_height / char_count

        char_bboxes = []
        for i in range(char_count):
            char_y1 = y1 + margin + i * (char_height + margin)
            char_y2 = y1 + margin + (i + 1) * char_height + i * margin
            char_bboxes.append([x1, char_y1, x2, char_y2])

        return char_bboxes

    def get_ordered_text(self, char_results: List[Dict[str, Any]]) -> str:
        """获取排序后的完整文字"""
        return "".join(r["char"] for r in char_results)

    def process_from_text(
        self,
        text: str,
        image_width: Optional[int] = None,
        image_height: Optional[int] = None,
        columns: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        从纯文本生成单字结果（用于没有精确bbox的情况）

        根据图像尺寸和列数估算每个字的bbox。

        Args:
            text: 识别的文本
            image_width: 图像宽度
            image_height: 图像高度
            columns: 列数

        Returns:
            单字结果列表
        """
        if not text:
            return []

        # 清理文本：移除空白字符
        clean_text = text.replace(" ", "").replace("\n", "").replace("\r", "")
        if not clean_text:
            return []

        use_text = clean_text

        # 估算尺寸
        if image_width and image_height:
            char_width = image_width / columns
            char_height = image_height / (len(use_text) / columns + 1)
            char_height = max(char_height, 20)  # 最小高度
        else:
            # 默认值
            char_width = 100
            char_height = 100

        char_results = []
        global_char_index = 0

        # 按列分组
        chars_per_column = len(use_text) // columns
        if chars_per_column == 0:
            chars_per_column = 1

        for col_idx in range(columns):
            # 计算这一列的起始和结束位置
            start_idx = col_idx * chars_per_column
            end_idx = min(start_idx + chars_per_column, len(use_text))

            if start_idx >= len(use_text):
                break

            # 计算这一列的x坐标范围
            col_x1 = col_idx * char_width
            col_x2 = (col_idx + 1) * char_width

            for row_idx, char_idx in enumerate(range(start_idx, end_idx)):
                if char_idx >= len(use_text):
                    break

                char = use_text[char_idx]

                # 计算这一列中当前行的y坐标
                row_y1 = row_idx * char_height
                row_y2 = (row_idx + 1) * char_height

                char_results.append({
                    "char": char,
                    "bbox": [col_x1, row_y1, col_x2, row_y2],
                    "column": col_idx,
                    "row": row_idx,
                    "char_in_text": char_idx,
                    "global_index": global_char_index,
                })
                global_char_index += 1

        return char_results


class VerticalTextLayoutAnalyzer:
    """
    竖排文字布局分析器
    用于更精确地分析书法作品的列结构
    """

    def __init__(self):
        pass

    def analyze_layout(
        self,
        ocr_results: List[Dict[str, Any]],
        image_width: int,
        image_height: int,
    ) -> Dict[str, Any]:
        """
        分析整体布局

        Args:
            ocr_results: OCR结果
            image_width: 图像宽度
            image_height: 图像高度

        Returns:
            布局信息字典
        """
        if not ocr_results:
            return {"columns": [], "total_chars": 0}

        # 分析列
        columns = self._detect_columns(ocr_results, image_width)

        # 统计信息
        total_chars = sum(len(col.get("text", "")) for col in columns)

        return {
            "columns": columns,
            "total_chars": total_chars,
            "column_count": len(columns),
            "image_width": image_width,
            "image_height": image_height,
        }

    def _detect_columns(
        self,
        ocr_results: List[Dict[str, Any]],
        image_width: int,
    ) -> List[Dict[str, Any]]:
        """
        检测列

        Args:
            ocr_results: OCR结果
            image_width: 图像宽度

        Returns:
            列列表
        """
        if not ocr_results:
            return []

        # 使用x坐标聚类
        centers = []
        for item in ocr_results:
            bbox = item["bbox"]
            center_x = (bbox[0] + bbox[2]) / 2
            centers.append(center_x)

        # 简单聚类：使用距离阈值
        avg_width = np.mean([item["bbox"][2] - item["bbox"][0] for item in ocr_results])
        threshold = avg_width * 0.5

        # 排序中心点
        sorted_centers = sorted(set(centers))

        # 聚类
        clusters = []
        current_cluster = [sorted_centers[0]]

        for i in range(1, len(sorted_centers)):
            if sorted_centers[i] - current_cluster[-1] < threshold:
                current_cluster.append(sorted_centers[i])
            else:
                clusters.append(np.mean(current_cluster))
                current_cluster = [sorted_centers[i]]

        if current_cluster:
            clusters.append(np.mean(current_cluster))

        # 分配OCR结果到列
        columns = []
        for cluster_center in clusters:
            col_items = [
                item for item in ocr_results
                if abs((item["bbox"][0] + item["bbox"][2]) / 2 - cluster_center) < threshold
            ]
            if col_items:
                # 按y坐标排序
                col_items.sort(key=lambda x: x["bbox"][1])
                columns.append({
                    "center_x": cluster_center,
                    "items": col_items,
                    "text": "".join(item["text"] for item in col_items),
                })

        # 从右向左排序
        columns.sort(key=lambda col: -col["center_x"])

        return columns
