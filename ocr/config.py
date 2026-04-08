"""
OCR Configuration Module
书法拆字识别配置
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 从项目根目录加载 .env 文件
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

# API Configuration - Layout Parsing API
API_URL = os.environ.get("OCR_API_URL", "")
API_TOKEN = os.environ.get("OCR_API_TOKEN", "")

# Request Configuration
REQUEST_TIMEOUT = 60  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 1  # seconds

# Chinese Calligraphy Layout Configuration
# 竖排文字：从右上角开始，从右向左、从上往下
VERTICAL_LAYOUT = {
    "direction": "right_to_left",  # 列的排列方向
    "column_direction": "top_to_bottom",  # 列内文字排列方向
    "min_column_width": 30,  # 最小列宽（像素）
    "min_column_height": 100,  # 最小列高（像素）
}

# Character BBox Estimation
CHAR_BBOX = {
    "use_uniform_split": True,  # 使用均匀分割（书法文字间隔均匀）
    "min_char_height": 20,  # 最小字高
    "min_char_width": 20,  # 最小字宽
    "overlap_threshold": 0.3,  # bbox重叠阈值
    # 分割策略配置
    "split_method": "hybrid",  # 分割方法: uniform, pixel, hybrid
    "margin_ratio": 0.05,  # 均分边距比例
    "projection_threshold_ratio": 0.1,  # 投影阈值比例
}

# Output Configuration
OUTPUT_DIR = "ocr_output"
SAVE_DEBUG_IMAGES = True  # 保存调试图片
