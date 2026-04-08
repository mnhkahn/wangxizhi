"""
Image Preprocessing Module
图像预处理模块
"""

import cv2
import numpy as np
from typing import Tuple, Optional
from pathlib import Path


class ImagePreprocessor:
    """图像预处理器"""

    def __init__(self):
        self.original_image = None
        self.processed_image = None

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
