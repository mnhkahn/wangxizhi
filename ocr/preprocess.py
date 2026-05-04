"""
Image Preprocessing Module
图像预处理模块
"""

import cv2
import numpy as np
from typing import Tuple, Optional
from pathlib import Path


def _longest_run(mask: np.ndarray):
    """找到布尔数组中最长的连续 True 段。"""
    best_start, best_end, best_len = 0, 0, 0
    current_start = None
    for i, v in enumerate(mask):
        if v:
            if current_start is None:
                current_start = i
        else:
            if current_start is not None:
                length = i - current_start
                if length > best_len:
                    best_len = length
                    best_start = current_start
                    best_end = i - 1
                current_start = None
    if current_start is not None:
        length = len(mask) - current_start
        if length > best_len:
            best_len = length
            best_start = current_start
            best_end = len(mask) - 1
    return best_start, best_end, best_len


def detect_content_region(gray: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """
    检测图像中的黑色主体内容区域，用于裁剪掉白色边框。

    策略：
    1. 对黑底白字碑帖，通过暗色像素（<100）的比例定位主体区域
    2. 如果中心区域本身就很暗且四边没有明显白色边框，返回 None

    Returns:
        裁剪框 (x1, y1, x2, y2) 或 None（无需裁剪）
    """
    h, w = gray.shape

    # 计算暗色像素（<100）在每行/每列的比例
    dark_mask = gray < 100
    row_dark_ratio = dark_mask.mean(axis=1)
    col_dark_ratio = dark_mask.mean(axis=0)

    # 主体区域：暗色像素比例 > 30%
    row_mask = row_dark_ratio > 0.30
    col_mask = col_dark_ratio > 0.30

    ry1, ry2, rh = _longest_run(row_mask)
    rx1, rx2, rw = _longest_run(col_mask)

    if rh > h * 0.3 and rw > w * 0.3:
        # 增加少量 padding
        pad = 5
        rx1 = max(0, rx1 - pad)
        ry1 = max(0, ry1 - pad)
        rx2 = min(w - 1, rx2 + pad)
        ry2 = min(h - 1, ry2 + pad)
        return (rx1, ry1, rx2, ry2)

    return None


def tighten_char_bbox(image: np.ndarray, bbox: list, pad: int = 3) -> list:
    """
    收紧单字 bbox，去掉白边（相邻字笔画、列内空白、边框线）。

    策略：
    1. Otsu 二值化分离前景（字）和背景
    2. 去除整列/整行超过 80% 为前景的边框线
    3. 在剩余区域中找到实际有前景的边界
    4. 加回少量 padding

    Args:
        image: 原图（numpy array）
        bbox: [x1, y1, x2, y2]
        pad: 收紧后保留的边距像素

    Returns:
        收紧后的 bbox [x1, y1, x2, y2]
    """
    import cv2
    import numpy as np

    x1, y1, x2, y2 = [int(v) for v in bbox]
    h, w = image.shape[:2]
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(w, x2)
    y2 = min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return bbox

    crop = image[y1:y2, x1:x2]
    if len(crop.shape) == 3:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    else:
        gray = crop

    # Otsu 二值化
    is_dark_bg = float(np.mean(gray)) < 128
    if is_dark_bg:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    bh, bw = binary.shape

    # 检测并去除边框列/行（整列/整行超过 80% 为前景）
    left_border = 0
    for col in range(bw):
        if np.sum(binary[:, col] > 0) > bh * 0.8:
            left_border = col + 1
        else:
            break

    right_border = bw
    for col in range(bw - 1, -1, -1):
        if np.sum(binary[:, col] > 0) > bh * 0.8:
            right_border = col
        else:
            break

    top_border = 0
    for row in range(bh):
        if np.sum(binary[row, :] > 0) > bw * 0.8:
            top_border = row + 1
        else:
            break

    bottom_border = bh
    for row in range(bh - 1, -1, -1):
        if np.sum(binary[row, :] > 0) > bw * 0.8:
            bottom_border = row
        else:
            break

    if left_border >= right_border or top_border >= bottom_border:
        return bbox

    binary = binary[top_border:bottom_border, left_border:right_border]

    # 在去除边框后的区域找到实际内容边界
    col_mask = np.any(binary > 0, axis=0)
    row_mask = np.any(binary > 0, axis=1)
    cols = np.where(col_mask)[0]
    rows = np.where(row_mask)[0]

    if len(cols) > 0:
        cx1 = max(0, cols[0] - pad)
        cx2 = min(binary.shape[1], cols[-1] + 1 + pad)
    else:
        cx1, cx2 = 0, binary.shape[1]

    if len(rows) > 0:
        cy1 = max(0, rows[0] - pad)
        cy2 = min(binary.shape[0], rows[-1] + 1 + pad)
    else:
        cy1, cy2 = 0, binary.shape[0]

    return [
        float(x1 + left_border + cx1),
        float(y1 + top_border + cy1),
        float(x1 + left_border + cx2),
        float(y1 + top_border + cy2),
    ]


class ImagePreprocessor:
    """图像预处理器"""

    def __init__(self):
        self.original_image = None
        self.processed_image = None
        self.crop_offset = (0, 0)  # (x, y) 裁剪偏移量

    def load_image(self, image_path: str) -> np.ndarray:
        """
        加载图像

        Args:
            image_path: 图像文件路径

        Returns:
            numpy数组格式的图像
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        self.original_image = cv2.imread(str(path))
        if self.original_image is None:
            raise ValueError(f"Failed to load image: {image_path}")

        self.processed_image = self.original_image.copy()
        return self.original_image

    def load_from_array(self, image_array: np.ndarray) -> np.ndarray:
        """
        从numpy数组加载图像

        Args:
            image_array: numpy数组格式的图像

        Returns:
            原始图像
        """
        self.original_image = image_array.copy()
        self.processed_image = self.original_image.copy()
        return self.original_image

    def enhance_for_ocr(self) -> np.ndarray:
        """
        增强图像以优化OCR效果

        Returns:
            增强后的图像
        """
        if self.processed_image is None:
            raise ValueError("No image loaded")

        # 转为灰度图
        if len(self.processed_image.shape) == 3:
            gray = cv2.cvtColor(self.processed_image, cv2.COLOR_BGR2GRAY)
        else:
            gray = self.processed_image.copy()

        # 自适应直方图均衡化
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # 转回BGR格式（API可能需要彩色图）
        self.processed_image = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)

        return self.processed_image

    def crop_to_content(self) -> Tuple[np.ndarray, Tuple[int, int]]:
        """
        裁剪掉白色边框，保留黑色主体内容区域。

        如果检测到黑色主体区域，会更新 processed_image 并记录裁剪偏移量。

        Returns:
            元组 (裁剪后的图像, (offset_x, offset_y))
        """
        if self.processed_image is None:
            raise ValueError("No image loaded")

        if len(self.processed_image.shape) == 3:
            gray = cv2.cvtColor(self.processed_image, cv2.COLOR_BGR2GRAY)
        else:
            gray = self.processed_image.copy()

        bbox = detect_content_region(gray)
        if bbox is not None:
            x1, y1, x2, y2 = bbox
            self.processed_image = self.processed_image[y1:y2+1, x1:x2+1]
            self.crop_offset = (x1, y1)
            if self.original_image is not None:
                self.original_image = self.original_image[y1:y2+1, x1:x2+1]
        else:
            self.crop_offset = (0, 0)

        return self.processed_image, self.crop_offset

    def get_image_info(self) -> dict:
        """
        获取图像基本信息

        Returns:
            包含图像信息的字典
        """
        if self.original_image is None:
            raise ValueError("No image loaded")

        height, width = self.original_image.shape[:2]
        return {
            "width": width,
            "height": height,
            "channels": self.original_image.shape[2] if len(self.original_image.shape) == 3 else 1,
            "dtype": str(self.original_image.dtype),
        }

    def resize_if_needed(self, max_size: int = 2000) -> Tuple[np.ndarray, float]:
        """
        如果图像过大，进行缩放

        Args:
            max_size: 最大边长

        Returns:
            元组 (处理后的图像, 缩放比例)
        """
        if self.processed_image is None:
            raise ValueError("No image loaded")

        height, width = self.processed_image.shape[:2]
        scale = 1.0

        if max(height, width) > max_size:
            scale = max_size / max(height, width)
            new_width = int(width * scale)
            new_height = int(height * scale)
            self.processed_image = cv2.resize(
                self.processed_image,
                (new_width, new_height),
                interpolation=cv2.INTER_AREA
            )

        return self.processed_image, scale

    def encode_to_base64(self, format: str = ".jpg") -> str:
        """
        将图像编码为base64字符串

        Args:
            format: 图像格式（.jpg, .png等）

        Returns:
            base64编码的字符串
        """
        import base64

        if self.processed_image is None:
            raise ValueError("No image loaded")

        _, buffer = cv2.imencode(format, self.processed_image)
        return base64.b64encode(buffer).decode('utf-8')

    def draw_bboxes(
        self,
        bboxes: list,
        output_path: Optional[str] = None,
        color: Tuple[int, int, int] = (0, 255, 0),
        thickness: int = 2
    ) -> np.ndarray:
        """
        在图像上绘制边界框

        Args:
            bboxes: 边界框列表，每个为 [x1, y1, x2, y2] 格式
            output_path: 输出路径（可选）
            color: 边框颜色
            thickness: 线宽

        Returns:
            绘制后的图像
        """
        if self.original_image is None:
            raise ValueError("No image loaded")

        image_with_bboxes = self.original_image.copy()

        for bbox in bboxes:
            x1, y1, x2, y2 = [int(v) for v in bbox]
            cv2.rectangle(image_with_bboxes, (x1, y1), (x2, y2), color, thickness)

        if output_path:
            cv2.imwrite(output_path, image_with_bboxes)

        return image_with_bboxes

    def draw_text_labels(
        self,
        bboxes: list,
        texts: list,
        output_path: Optional[str] = None,
        color: Tuple[int, int, int] = (0, 0, 255),
        font_scale: float = 0.5
    ) -> np.ndarray:
        """
        在图像上绘制文字标签

        Args:
            bboxes: 边界框列表
            texts: 文字列表
            output_path: 输出路径
            color: 文字颜色
            font_scale: 字体大小

        Returns:
            绘制后的图像
        """
        if self.original_image is None:
            raise ValueError("No image loaded")

        image_with_text = self.original_image.copy()

        for bbox, text in zip(bboxes, texts):
            x1, y1, x2, y2 = [int(v) for v in bbox]
            # 在边界框上方绘制文字
            cv2.putText(
                image_with_text,
                text,
                (x1, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                font_scale,
                color,
                1,
                cv2.LINE_AA
            )

        if output_path:
            cv2.imwrite(output_path, image_with_text)

        return image_with_text
