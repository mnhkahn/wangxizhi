"""
OCR Configuration Module
书法拆字识别配置
"""

import os

# API Configuration - Layout Parsing API
API_URL = "https://k71ai350v9z6pdud.aistudio-app.com/layout-parsing"
API_TOKEN = os.environ.get("OCR_API_TOKEN", "448d7ec0b4da8d1d64d1b9915f12022dcd4690c3")

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
}

# Known text for validation (校验用已知文字)
KNOWN_TEXTS = {
    "怀仁集王羲之圣教序/fatie-000.jpg": (
        "大唐三藏聖教序太宗文皇帝製和福寺沙门懷仁集晋右将军王羲之书"
        "盖闻二仪有像头霞载以含生四时气形滑寒暑以化物是以窺天鑑地庸愚"
    ),
}

# Output Configuration
OUTPUT_DIR = "ocr_output"
SAVE_DEBUG_IMAGES = True  # 保存调试图片
