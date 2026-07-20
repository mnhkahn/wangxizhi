"""
OCR Module for Chinese Calligraphy
书法拆字识别模块

使用方法:
    from ocr import CalligraphyOCR, recognize_calligraphy

    # 方法1: 使用便捷函数
    result = recognize_calligraphy("path/to/image.jpg", debug=True)

    # 方法2: 使用类
    ocr = CalligraphyOCR()
    result = ocr.recognize_image("path/to/image.jpg")

输出结果包含:
    - image_info: 图像信息
    - recognized_text: 识别的完整文字
    - char_results: 每个字的详细信息（文本、bbox、列号、行号）
    - ocr_results: 原始OCR检测结果
"""

from .config import (
    API_URL,
    API_TOKEN,
    VERTICAL_LAYOUT,
    CHAR_BBOX,
    OUTPUT_DIR,
)
from .preprocess import ImagePreprocessor
from .api_client import OCRAPIClient
from .postprocess import CalligraphyPostprocessor, VerticalTextLayoutAnalyzer
from .char_splitter import CharSplitter, SplitMethod, split_column_to_chars
from .recognizer import CalligraphyOCR, recognize_calligraphy

__all__ = [
    # 主接口
    "CalligraphyOCR",
    "recognize_calligraphy",
    # 组件
    "ImagePreprocessor",
    "OCRAPIClient",
    "CalligraphyPostprocessor",
    "VerticalTextLayoutAnalyzer",
    "CharSplitter",
    "SplitMethod",
    "split_column_to_chars",
    # 配置
    "API_URL",
    "API_TOKEN",
    "VERTICAL_LAYOUT",
    "CHAR_BBOX",
    "OUTPUT_DIR",
]

__version__ = "1.0.0"
