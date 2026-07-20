#!/usr/bin/env python
"""
书法拆字编辑器 - 启动脚本
"""

import sys
from pathlib import Path

import os

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 加载项目根目录下的 .env（用于 OCR/上传等配置）
try:
    from dotenv import load_dotenv

    load_dotenv(project_root / ".env")
except Exception:
    # 允许在未安装 python-dotenv 时继续启动
    pass

from app.main import main

if __name__ == "__main__":
    main()
