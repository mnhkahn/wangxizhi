"""
书法拆字编辑器 - 应用入口
"""

import sys
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 支持直接以 ``python -m app.main`` 或打包入口启动时读取项目配置。
# ``run_app.py`` 也会加载一次；重复加载是安全的。
try:
    from dotenv import load_dotenv

    load_dotenv(project_root / ".env")
except Exception:
    # 缺少 python-dotenv 时仍允许桌面应用启动。
    pass

from .main_window import MainWindow
from .utils.fonts import load_embedded_fonts


def main():
    """主函数"""
    # 高 DPI 支持
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    load_embedded_fonts()
    app.setApplicationName("书法拆字编辑器")
    app.setApplicationVersion("1.0.0")

    # 设置应用图标
    icon_path = Path(__file__).parent / "assets" / "icon.png"
    if icon_path.exists():
        app_icon = QIcon(str(icon_path))
        app.setWindowIcon(app_icon)

    # 设置样式
    app.setStyle("Fusion")

    # 创建主窗口
    window = MainWindow()
    if icon_path.exists():
        window.setWindowIcon(app_icon)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
